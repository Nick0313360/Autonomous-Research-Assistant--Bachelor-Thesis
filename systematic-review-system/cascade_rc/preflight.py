"""
cascade_rc/preflight.py
=======================
Fast pre-flight checks for the CASCADE-RC pipeline.

Designed to catch silent failures (SHA mismatches, broken cache, unreachable
endpoints) in under 30 seconds, before expensive multi-hour steps begin.

Usage (automatic — called from run_pipeline.py):
    step_score_u calls: run_preflight([check_llm_endpoint(...), check_cache_writable(...)])
    step_merge_u calls: run_preflight([check_parquet_schema(...), check_cache_sha_sample(...), ...])

Usage (manual):
    python -m cascade_rc.preflight --topic CD008874
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

PASS = "✓"
FAIL = "✗"
WARN = "~"


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    detail: str = ""
    warning_only: bool = False  # True → print warning but don't abort


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_parquet_schema(parquet_path: Path, topic_id: str) -> CheckResult:
    """Verify parquet exists, has required columns, and contains rows for topic."""
    required = {"pmid", "title", "abstract", "s", "y_abstract"}
    name = "parquet_schema"

    if not parquet_path.exists():
        return CheckResult(name, False, f"Parquet not found: {parquet_path}")

    try:
        df = pd.read_parquet(parquet_path)
    except Exception as exc:
        return CheckResult(name, False, f"Cannot read parquet: {exc}")

    if len(df) == 0:
        return CheckResult(name, False, "Parquet is empty (0 rows)")

    missing = required - set(df.columns)
    if missing:
        return CheckResult(name, False, f"Missing columns: {sorted(missing)}", f"Present: {sorted(df.columns)}")

    # Check topic filtering
    if "topic_id" in df.columns:
        topic_rows = int((df["topic_id"] == topic_id).sum())
        if topic_rows == 0:
            return CheckResult(
                name, False,
                f"No rows for topic_id={topic_id!r} in parquet ({len(df)} total rows)",
                f"Topics present: {df['topic_id'].unique().tolist()[:10]}",
            )
        detail = f"{topic_rows}/{len(df)} rows for {topic_id}, columns {sorted(df.columns)}"
    else:
        detail = f"{len(df)} rows, columns {sorted(df.columns)}"

    s_nonzero = int((df["s"] > 0.0).sum())
    if s_nonzero == 0:
        return CheckResult(name, False, "All s scores are 0.0 — step_score_s may not have run", detail)

    return CheckResult(name, True, detail)


def check_cache_sha_sample(
    parquet_path: Path,
    cache_path: Path,
    topic_id: str,
    sample_n: int = 20,
    seed: int = 42,
) -> CheckResult:
    """
    Sample *sample_n* PMIDs and verify that the SHA computed by step_merge_u
    hits the cache.  A 0% hit rate means step_score_u and step_merge_u are
    computing different SHAs — the exact failure mode that causes θ̂=0.0.
    """
    from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache
    from cascade_rc.run_pipeline import _load_pico
    from infrastructure.llm_client import LLMClient
    from tier2_screening.abstract_screener import _TEMPLATE, _fill_template
    from cascade_rc.cache.llm_ensemble import _CRITERION_TEXT

    name = "cache_sha_sample"

    if not cache_path.exists():
        return CheckResult(name, False, f"Cache DB not found: {cache_path}")

    try:
        df = pd.read_parquet(parquet_path)
    except Exception as exc:
        return CheckResult(name, False, f"Cannot read parquet: {exc}")

    if "topic_id" in df.columns:
        df = df[df["topic_id"] == topic_id].copy()

    # Only sample rows with abstracts (same set step_score_u would process)
    df_with_abs = df[df["abstract"].notna() & (df["abstract"].astype(str).str.len() > 0)]
    if len(df_with_abs) == 0:
        return CheckResult(name, False, "No rows with abstracts — cannot verify SHA consistency")

    rng = random.Random(seed)
    sample = df_with_abs.sample(n=min(sample_n, len(df_with_abs)), random_state=rng.randint(0, 2**31)).copy()

    pico = _load_pico(topic_id, [parquet_path.parent, Path(".")])
    pico_text = (
        f"Population: {pico['population']}\n"
        f"Intervention: {pico['intervention']}\n"
        f"Comparator: {pico['comparator']}\n"
        f"Outcome: {pico['outcome']}\n"
        f"Study design: {pico['study_design']}"
    )

    try:
        cache = SQLiteEnsembleCache(cache_path)
    except Exception as exc:
        return CheckResult(name, False, f"Cannot open cache DB: {exc}")

    hits = 0
    example_pmid: Optional[str] = None
    example_sha_merge: Optional[str] = None
    example_sha_cache: Optional[str] = None

    for _, row in sample.iterrows():
        pmid = str(row["pmid"])
        title = str(row.get("title", ""))
        abstract = str(row.get("abstract", ""))

        prompt = _fill_template(
            _TEMPLATE,
            pico_text=pico_text,
            criterion_text=_CRITERION_TEXT,
            title=title,
            abstract=abstract,
        )
        sha = hashlib.sha256(prompt.encode()).hexdigest()

        rows_cached = cache.fetch_ensemble(
            model_id=LLMClient.GPT_MODEL,
            prompt_sha=sha,
            pmid=pmid,
            temperature=0.7,
            template_v="v1",
            B=5,
        )
        if len(rows_cached) == 5:
            hits += 1
        elif example_pmid is None:
            # Grab the actual SHA stored in the DB for this PMID for the error report
            example_pmid = pmid
            example_sha_merge = sha
            example_sha_cache = _get_stored_sha(cache_path, pmid)

    cache.close()

    n_sampled = len(sample)
    hit_rate = hits / n_sampled

    if hit_rate == 0.0:
        detail_lines = [f"merge_u SHA : {example_sha_merge}"]
        if example_sha_cache:
            detail_lines.append(f"cache SHA   : {example_sha_cache}")
            detail_lines.append("Likely cause: abstract truncation or PICO mismatch between step_score_u and step_merge_u")
        else:
            detail_lines.append("No entries at all in cache for this PMID — step_score_u may not have run")
        detail_lines.append("Fix: re-run --resume-from score_u, or verify _load_pico() returns identical dicts in both steps")
        return CheckResult(
            name, False,
            f"Cache hit rate 0/{n_sampled} (0%) for topic {topic_id} — step_merge_u will fall back to u=s for ALL docs",
            "\n      ".join(detail_lines),
        )

    if hit_rate < 0.5:
        return CheckResult(
            name, False,
            f"Cache hit rate {hits}/{n_sampled} ({hit_rate:.0%}) — majority of u scores will fall back to s",
            f"First miss: PMID {example_pmid}, merge_u SHA={example_sha_merge}",
        )

    if hit_rate < 1.0:
        return CheckResult(
            name, True,
            f"Cache hit rate {hits}/{n_sampled} ({hit_rate:.0%}) — some PMIDs will fall back to u=s",
            warning_only=True,
        )

    return CheckResult(name, True, f"Cache hit rate {hits}/{n_sampled} (100%)")


def _get_stored_sha(cache_path: Path, pmid: str) -> Optional[str]:
    """Return the first prompt_sha stored for *pmid* in the cache, or None."""
    try:
        con = sqlite3.connect(cache_path)
        row = con.execute(
            "SELECT prompt_sha FROM llm_calls WHERE pmid = ? LIMIT 1", (pmid,)
        ).fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


def check_pico_loaded(parquet_path: Path, topic_id: str) -> CheckResult:
    """
    Warn when no protocol JSON is found — the LLM will screen with empty PICO,
    which means it has no inclusion criteria and defaults to excluding everything.
    """
    from cascade_rc.run_pipeline import _load_pico

    name = "pico_loaded"
    pico = _load_pico(topic_id, [parquet_path.parent, Path(".")])
    empty_fields = [k for k, v in pico.items() if not v]

    if len(empty_fields) == len(pico):
        return CheckResult(
            name, True,
            f"No protocol JSON found — all PICO fields empty. "
            f"Place {topic_id}_protocol.json next to the parquet to enable PICO-aware screening.",
            warning_only=True,
        )

    if empty_fields:
        return CheckResult(
            name, True,
            f"Partial PICO loaded (empty fields: {empty_fields})",
            f"population={pico['population'][:60]!r}",
            warning_only=True,
        )

    return CheckResult(
        name, True,
        f"PICO loaded — population={pico['population'][:60]!r}",
    )


def check_llm_endpoint(endpoint_url: str, timeout_s: int = 5) -> CheckResult:
    """Verify the BFH LLM endpoint responds before the 1799-PMID loop starts."""
    name = "llm_endpoint"
    # Probe the /models endpoint which is a lightweight GET on OpenAI-compatible APIs
    probe = endpoint_url.rstrip("/") + "/models"
    try:
        req = urllib.request.Request(probe, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = resp.status
        return CheckResult(name, True, f"Endpoint reachable ({probe}, HTTP {status})")
    except urllib.error.HTTPError as exc:
        # 4xx means the server is up and responding — auth/routing issues are
        # expected for unauthenticated probes and do not block the pipeline.
        if exc.code < 500:
            return CheckResult(name, True, f"Endpoint reachable ({probe}, HTTP {exc.code})")
        return CheckResult(name, False, f"Endpoint server error ({probe}, HTTP {exc.code})")
    except Exception as exc:
        return CheckResult(
            name, False,
            f"Endpoint unreachable: {probe}",
            f"{type(exc).__name__}: {exc}\n      Fix: check VPN / BFH network access",
        )


def check_cache_writable(cache_path: Path) -> CheckResult:
    """Verify the SQLite cache file can be opened for writing."""
    name = "cache_writable"
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(cache_path, timeout=3)
        con.execute("SELECT 1")
        con.close()
        return CheckResult(name, True, f"Cache writable: {cache_path}")
    except sqlite3.OperationalError as exc:
        return CheckResult(
            name, False,
            f"Cannot open cache for writing: {cache_path}",
            f"{exc}\n      Fix: check file permissions or whether another process holds a lock",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class PreflightError(RuntimeError):
    pass


def run_preflight(checks: list[CheckResult]) -> None:
    """
    Print a result table for *checks* and raise PreflightError if any
    non-warning check failed.

    Warnings (warning_only=True) are printed but never cause an abort.
    """
    failures: list[CheckResult] = []
    lines: list[str] = []

    for c in checks:
        if c.passed:
            symbol = WARN if c.warning_only else PASS
            lines.append(f"  {symbol} {c.name:<28} {c.message}")
        else:
            symbol = WARN if c.warning_only else FAIL
            lines.append(f"  {symbol} {c.name:<28} {c.message}")
            if c.detail:
                for dline in c.detail.split("\n"):
                    lines.append(f"      {dline}")
            if not c.warning_only:
                failures.append(c)

    separator = "-" * 60
    header = "PREFLIGHT" + (" FAILED" if failures else " OK")
    print(separator)
    print(header)
    print("\n".join(lines))
    print(separator)

    if failures:
        names = ", ".join(c.name for c in failures)
        raise PreflightError(
            f"Pipeline aborted — {len(failures)} preflight check(s) failed: {names}\n"
            "Fix the issues above before re-running."
        )


# ---------------------------------------------------------------------------
# CLI — run all checks for a topic manually
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import sys

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(
        description="Run CASCADE-RC preflight checks for a topic.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", required=True)
    parser.add_argument("--parquet-dir", type=Path, default=Path("artefacts/cascade_rc/data"))
    parser.add_argument("--cache-path", type=Path, default=Path("artefacts/cascade_rc/llm_cache.db"))
    parser.add_argument("--endpoint", default="https://inference.mlmp.ti.bfh.ch/api/v1")
    parser.add_argument("--sample-n", type=int, default=20)
    parser.add_argument("--skip-endpoint", action="store_true", help="Skip LLM endpoint check")
    args = parser.parse_args()

    parquet_path = args.parquet_dir / f"{args.topic}.parquet"

    checks: list[CheckResult] = [
        check_parquet_schema(parquet_path, args.topic),
        check_pico_loaded(parquet_path, args.topic),
        check_cache_writable(args.cache_path),
        check_cache_sha_sample(parquet_path, args.cache_path, args.topic, args.sample_n),
    ]
    if not args.skip_endpoint:
        checks.append(check_llm_endpoint(args.endpoint))

    try:
        run_preflight(checks)
    except PreflightError as exc:
        print(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
