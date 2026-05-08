"""End-to-end orchestrator for CASCADE-RC systematic review pipeline.

Chains all steps from data ingestion to figure generation for a single topic,
or iterates over multiple topics when --topics is supplied.

Usage:
    python -m cascade_rc.run_pipeline --topic CD008874
    python -m cascade_rc.run_pipeline --topic CD008874 --skip-llm
    python -m cascade_rc.run_pipeline --topic CD008874 --resume-from calibrate

    # Multi-topic run with selective steps and resume:
    python -m cascade_rc.run_pipeline \\
        --topics CD008874 CD012080 CD012768 CD011768 CD011975 CD011145 \\
        --steps ingest score_s score_u merge_u baselines calibrate evaluate \\
        --resume \\
        --collect-summary
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _progress_print(msg: str, *, end: str = "\n") -> None:
    """Print progress directly to stdout (bypasses logging level filters)."""
    print(msg, end=end, flush=True)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]

TOPIC_FAMILY: dict[str, str] = {
    "CD008874": "DTA",
    "CD012080": "DTA",
    "CD012768": "DTA",
    "CD011768": "Intervention",
    "CD011975": "DTA",
    "CD011145": "DTA",
}

STEPS = [
    "ingest",
    "score_s",
    "score_u",
    "merge_u",
    "baselines",
    "calibrate",
    "evaluate",
    "figures",
]


# ---------------------------------------------------------------------------
# Resume helper — check if a step's output artefacts already exist
# ---------------------------------------------------------------------------

def _step_is_done(
    step: str,
    topic_id: str,
    out_dir: Path,
    artefact_dir: Path,
) -> bool:
    """Return True if the output artefacts for `step`/`topic_id` already exist."""
    parquet_path = out_dir / f"{topic_id}.parquet"
    if step == "ingest":
        return parquet_path.exists()
    if step == "score_s":
        if not parquet_path.exists():
            return False
        try:
            df_peek = pd.read_parquet(parquet_path, columns=["s"])
            return float(df_peek["s"].max()) > 0.05
        except Exception:
            return False
    if step == "score_u":
        return False  # SQLite cache handles per-PMID resumability natively
    if step == "merge_u":
        if not parquet_path.exists():
            return False
        try:
            df_peek = pd.read_parquet(parquet_path, columns=["s", "u"])
            return "u" in df_peek.columns and not bool((df_peek["u"] == df_peek["s"]).all())
        except Exception:
            return False
    if step == "baselines":
        return False  # cheap to re-run; no single canonical artefact per topic
    if step == "calibrate":
        return (artefact_dir / "certificates" / f"{topic_id}.pkl").exists()
    if step == "evaluate":
        return (artefact_dir / "routing" / f"{topic_id}.parquet").exists()
    if step == "figures":
        return False
    return False


# ---------------------------------------------------------------------------
# Step 0 (optional): Apply three-way split to existing parquet
# ---------------------------------------------------------------------------

def step_resplit(topic_id: str, parquet_path: Path, seed: int = 20260429) -> pd.DataFrame:
    """Apply three_way_split to an existing parquet and save it back.

    Replaces any existing 'is_split' column; also retains 'is_calib' for
    backwards compatibility with downstream code that reads it directly.
    """
    from cascade_rc.data.splits import three_way_split

    df = pd.read_parquet(parquet_path)
    total = len(df)
    print(f"[resplit] {topic_id}: applying three-way split to {parquet_path} ({total} rows)")
    df = three_way_split(df, seed=seed)

    split_counts = df.groupby("is_split").size()
    assert split_counts.sum() == total, "Row count changed after resplit"
    print(f"[resplit] Done — total={total} | " +
          " | ".join(f"is_split={k}: {v}" for k, v in sorted(split_counts.items())))

    df.to_parquet(parquet_path, index=False)
    logger.info("[resplit] Saved %s with is_split column", parquet_path)
    return df


# ---------------------------------------------------------------------------
# PICO loader — shared by step_score_u and step_merge_u
# ---------------------------------------------------------------------------

def _load_pico(topic_id: str, search_dirs: list[Path], _warn: bool = True) -> dict[str, str]:
    """Load PICO fields from {topic_id}_protocol.json.

    Searches each directory in *search_dirs* in order and returns the first
    match.  Falls back to empty strings when no file is found or parsing fails,
    which keeps the prompt format identical to the empty-PICO baseline so that
    previously cached SHA entries remain valid.

    Pass _warn=False to suppress the missing-file warning (e.g. when the
    preflight has already reported it).
    """
    empty: dict[str, str] = {
        "population": "", "intervention": "", "comparator": "",
        "outcome": "", "study_design": "",
    }
    for d in search_dirs:
        if d is None:
            continue
        candidate = d / f"{topic_id}_protocol.json"
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text())
            pico_raw = data.get("pico", {})
            return {
                "population":   str(pico_raw.get("population",   "") or ""),
                "intervention": str(pico_raw.get("intervention", "") or ""),
                "comparator":   str(pico_raw.get("comparator",   "") or ""),
                "outcome":      str(pico_raw.get("outcome",      "") or ""),
                "study_design": str(pico_raw.get("study_design", "") or ""),
            }
        except Exception as exc:
            logger.warning("Could not parse %s: %s — using empty PICO", candidate, exc)
    if _warn:
        logger.warning(
            "No protocol JSON found for %s (searched: %s) — PICO fields will be empty. "
            "Place %s_protocol.json in one of those directories to enable PICO-aware screening.",
            topic_id,
            [str(d) for d in search_dirs if d is not None],
            topic_id,
        )
    return empty


# ---------------------------------------------------------------------------
# Step 1: Ingest CLEF-TAR data
# ---------------------------------------------------------------------------

def step_ingest(topic_id: str, data_dir: Path, out_dir: Path) -> Path:
    """Download CLEF-TAR, fetch abstracts, create topic parquet."""
    from cascade_rc.data.clef_tar_loader import (
        download_clef_tar_2019,
        load_topic,
    )
    from cascade_rc.data.pubmed_fetch import fetch_abstracts as async_fetch
    from cascade_rc.data.splits import stratified_calib_test_split
    from cascade_rc.config import CascadeRCConfig

    parquet_path = out_dir / f"{topic_id}.parquet"
    if parquet_path.exists():
        logger.info("Step ingest: parquet exists, skipping (%s)", parquet_path)
        return parquet_path

    logger.info("Step ingest: downloading CLEF-TAR data …")
    clef_dir = download_clef_tar_2019(data_dir)

    logger.info("Step ingest: loading topic %s …", topic_id)
    topic = load_topic(topic_id, clef_dir)

    import asyncio
    cfg = CascadeRCConfig()
    logger.info("Step ingest: fetching abstracts for %d PMIDs …", len(topic.candidate_pmids))
    abstracts = asyncio.run(async_fetch(
        list(topic.candidate_pmids),
        email=cfg.ncbi_email,
        api_key=cfg.ncbi_api_key,
        cache_dir=out_dir / "pubmed",
    ))

    rows: list[dict] = []
    for pmid, qrel in topic.qrels_abstract.items():
        ab_rec = abstracts.get(pmid)
        rows.append({
            "pmid": pmid,
            "title": ab_rec["title"] if ab_rec else "",
            "abstract": ab_rec["abstract"] if ab_rec else None,
            "y_abstract": qrel,
            "is_calib": 0,
        })

    df = pd.DataFrame(rows)
    df["y_abstract"] = df["y_abstract"].astype("int8")
    df["is_calib"] = df["is_calib"].astype("int8")

    split_path = out_dir / "splits" / f"{topic_id}.parquet"
    calib_df, test_df = stratified_calib_test_split(
        df,
        calib_frac=0.5,
        fallback_8020_when_m_plus_at_least=26,
        seed=20260429,
        out_path=split_path,
    )

    is_calib_map: dict[str, int] = {}
    for _, row in calib_df.iterrows():
        is_calib_map[row["pmid"]] = 1
    for _, row in test_df.iterrows():
        is_calib_map[row["pmid"]] = 0

    final_rows = [
        {
            "pmid": r["pmid"],
            "title": r["title"],
            "abstract": r["abstract"],
            "y_abstract": r["y_abstract"],
            "is_calib": is_calib_map.get(r["pmid"], 0),
        }
        for r in rows
    ]

    df_final = pd.DataFrame(final_rows)
    df_final["y_abstract"] = df_final["y_abstract"].astype("int8")
    df_final["is_calib"] = df_final["is_calib"].astype("int8")
    df_final.to_parquet(parquet_path, index=False)

    n_pos = int((df_final["y_abstract"] == 1).sum())
    logger.info("Step ingest: %s written (%d rows, %d positives)", parquet_path, len(df_final), n_pos)
    return parquet_path


# ---------------------------------------------------------------------------
# Step 2: Score relevance (s column)
# ---------------------------------------------------------------------------

def step_score_s(topic_id: str, parquet_path: Path, data_dir: Path) -> pd.DataFrame:
    """Compute BM25 + SPECTER2 hybrid RRF scores and add s/u columns."""
    from cascade_rc.data.clef_tar_loader import load_topic
    from cascade_rc.data.update_parquet import add_scores_to_parquet

    df = pd.read_parquet(parquet_path)
    s_col = df["s"] if "s" in df.columns else None
    already_calibrated = (
        s_col is not None
        and s_col.notna().all()
        and float(s_col.max()) > 0.05
    )
    if already_calibrated:
        logger.info("Step score_s: s column already calibrated (max=%.4f), skipping", float(s_col.max()))
        return df

    try:
        topic = load_topic(topic_id, data_dir)
        query = f"{topic.title} {topic.boolean_query}"
    except Exception as exc:
        logger.warning("Could not load topic metadata (%s); using topic_id as query.", exc)
        query = topic_id

    logger.info("Step score_s: computing hybrid RRF scores for %s …", topic_id)
    df = add_scores_to_parquet(parquet_path, query)
    logger.info("Step score_s: s/u columns added (u=s placeholder)")
    return df


# ---------------------------------------------------------------------------
# Step 3: Score LLM (u column — populate SQLite cache)
# ---------------------------------------------------------------------------

def step_score_u(
    topic_id: str,
    parquet_path: Path,
    cache_path: Path,
    temperature: float = 0.7,
    n_calls: int = 5,
    max_failures: int = 10,
    dry_run: bool = False,
) -> None:
    """Run B=n_calls LLM ensemble and cache results in SQLite."""
    from cascade_rc.cache.llm_ensemble import run_score_u_async
    from cascade_rc.config import CascadeRCConfig
    from infrastructure.llm_client import LLMClient
    from cascade_rc.preflight import (
        check_llm_endpoint, check_cache_writable, check_pico_loaded, run_preflight,
    )

    cfg = CascadeRCConfig()

    run_preflight([
        check_cache_writable(cache_path),
        check_pico_loaded(parquet_path, topic_id),
        check_llm_endpoint(cfg.llm_endpoint),
    ])

    df = pd.read_parquet(parquet_path)
    pico = _load_pico(topic_id, [parquet_path.parent, Path(".")], _warn=False)

    # Silence per-slot HTTP and LLM noise; score_topic_async logs progress at 50-PMID intervals
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("cascade_rc.cache.llm_ensemble").setLevel(logging.WARNING)

    n_total = len(df)
    n_with_abstract = int(
        df["abstract"].notna().sum() if "abstract" in df.columns else 0
    )
    logger.info(
        "[score_u] %s — %d PMIDs to process (%d skipped, no abstract) | concurrency=%d",
        topic_id, n_with_abstract, n_total - n_with_abstract, cfg.n_concurrent,
    )

    stats = run_score_u_async(
        df=df,
        pico=pico,
        model_id=LLMClient.GPT_MODEL,
        temperature=temperature,
        B=n_calls,
        cache_path=cache_path,
        n_concurrent=cfg.n_concurrent,
        template_v="v1",
        max_failures=max_failures,
    )

    if stats.get("aborted"):
        logger.error("[score_u] Pipeline aborted after ensemble failures — see warnings above")
        sys.exit(1)

    logger.info(
        "[score_u] Done — %d PMIDs in %.1fs (%.1f PMIDs/min) | cache: %s",
        stats["processed"], stats["elapsed_s"], stats["rate_pmids_per_min"],
        json.dumps(stats.get("cache_stats", {})),
    )


# ---------------------------------------------------------------------------
# Step 4: Merge u scores from SQLite into parquet
# ---------------------------------------------------------------------------

def step_merge_u(topic_id: str, parquet_path: Path, cache_path: Path) -> pd.DataFrame:
    """Read LLM ensemble votes from SQLite, compute u per PMID, write to parquet."""
    from cascade_rc.preflight import (
        check_parquet_schema, check_cache_sha_sample, check_pico_loaded, run_preflight,
    )
    run_preflight([
        check_parquet_schema(parquet_path, topic_id),
        check_pico_loaded(parquet_path, topic_id),
        check_cache_sha_sample(parquet_path, cache_path, topic_id),
    ])
    import hashlib

    from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache
    from cascade_rc.cache.llm_ensemble import (
        _majority_and_u, _parse_vote, Vote, _CRITERION_TEXT,
    )
    from infrastructure.llm_client import LLMClient
    from tier2_screening.abstract_screener import _TEMPLATE, _fill_template

    df = pd.read_parquet(parquet_path)

    # Filter to the target topic when the parquet contains multiple topics.
    if "topic_id" in df.columns:
        before = len(df)
        df = df[df["topic_id"] == topic_id].copy()
        logger.info(
            "Step merge_u: topic filter %s — kept %d/%d rows",
            topic_id, len(df), before,
        )

    cache = SQLiteEnsembleCache(cache_path)

    # Build pico_text once — must be byte-identical to what screen_abstract_ensemble
    # produced during step_score_u so that prompt_sha lookup hits the cache.
    pico = _load_pico(topic_id, [parquet_path.parent, Path(".")], _warn=False)
    pico_text = (
        f"Population: {pico['population']}\n"
        f"Intervention: {pico['intervention']}\n"
        f"Comparator: {pico['comparator']}\n"
        f"Outcome: {pico['outcome']}\n"
        f"Study design: {pico['study_design']}"
    )

    u_map: dict[str, float] = {}
    y_hat_map: dict[str, int] = {}
    fallback_count = 0
    total = len(df)

    logger.info("[merge_u] %s — merging u scores for %d PMIDs", topic_id, total)

    for idx, (_, row) in enumerate(df.iterrows(), 1):
        pmid = str(row["pmid"])
        title = str(row.get("title", ""))
        abstract = str(row.get("abstract", ""))

        # Use the full abstract — do NOT truncate.  The prompt_sha stored by
        # step_score_u was computed with the full abstract; any truncation here
        # changes the SHA and causes a cache miss for every PMID.
        prompt = _fill_template(
            _TEMPLATE,
            pico_text=pico_text,
            criterion_text=_CRITERION_TEXT,
            title=title,
            abstract=abstract,
        )
        prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()

        rows_cached = cache.fetch_ensemble(
            model_id=LLMClient.GPT_MODEL,
            prompt_sha=prompt_sha,
            pmid=pmid,
            temperature=0.7,
            template_v="v1",
            B=5,
        )

        if len(rows_cached) == 5:
            # Re-parse from the stored response JSON rather than trusting vote_label.
            # Older cache runs stored vote_label='Uncertain' for responses like
            # {"satisfies": "true"} because the parser previously only checked
            # `is True` (Python bool), not `== "true"` (string).  Re-parsing here
            # corrects stale labels without touching the DB.
            votes: list[Vote] = [_parse_vote(r.get("response", {})) for r in rows_cached]
            majority, u, y_hat = _majority_and_u(votes, 5)
            u_map[pmid] = u
            y_hat_map[pmid] = y_hat
        else:
            fallback_count += 1
            logger.debug("[merge_u] PMID %s: only %d/5 cache rows, keeping u=s", pmid, len(rows_cached))

        if idx % 200 == 0 or idx == total:
            logger.info(
                "[merge_u] %d/%d (%.0f%%) | u_updates: %d | fallbacks: %d",
                idx, total, 100 * idx / total, len(u_map), fallback_count,
            )

    cache.close()

    if u_map:
        df["u"] = df["pmid"].astype(str).map(u_map).fillna(df["s"]).astype("float64")
        df["llm_y_hat"] = df["pmid"].astype(str).map(y_hat_map).fillna(0).astype("int64")
        df.to_parquet(parquet_path, index=False)
        u_vals = df["u"]
        logger.info(
            "[merge_u] Done — u updated for %d/%d PMIDs | fallbacks (u=s): %d "
            "| u stats: mean=%.4f  p50=%.4f  p95=%.4f  max=%.4f",
            len(u_map), total, fallback_count,
            float(u_vals.mean()), float(u_vals.quantile(0.50)),
            float(u_vals.quantile(0.95)), float(u_vals.max()),
        )
    else:
        logger.warning("[merge_u] No LLM scores found in cache — u remains equal to s for all PMIDs")

    return df


# ---------------------------------------------------------------------------
# Step 5: Run baselines (SCRC, AUTOSTOP, RLStop)
# ---------------------------------------------------------------------------

def step_baselines(topic_id: str, data_dir: Path, out_dir: Path) -> None:
    """Run SCRC, AUTOSTOP, and RLStop baselines for the topic."""
    from cascade_rc.baselines.scrc import run_sweep as scrc_sweep
    from cascade_rc.baselines.run_autostop import run_sweep as autostop_sweep
    from cascade_rc.baselines.run_rlstop import run_sweep as rlstop_sweep

    scrc_out = out_dir / "scrc"
    autostop_out = out_dir / "autostop"
    rlstop_out = out_dir / "rlstop"

    topics = [topic_id]

    logger.info("Step baselines: running SCRC …")
    scrc_sweep(data_dir=data_dir, out_dir=scrc_out, topics=topics)

    logger.info("Step baselines: running AUTOSTOP …")
    autostop_sweep(data_dir=data_dir, out_dir=autostop_out, topics=topics)

    logger.info("Step baselines: running RLStop …")
    _RLSTOP_VENDOR = Path(__file__).parent / "baselines" / "rlstop_vendor"
    _rlstop_qrels = _RLSTOP_VENDOR / "data" / "qrels" / "CLEF2017_qrels.txt"
    _rlstop_models = list(rlstop_out.glob("recall_*.zip")) if rlstop_out.exists() else []

    if _rlstop_qrels.exists():
        # Training data present — train and run normally
        rlstop_sweep(
            data_dir=data_dir, out_dir=rlstop_out, train_dir=rlstop_out,
            topics=topics, skip_train=False,
        )
    elif _rlstop_models:
        # Pre-trained weights present — skip training, run inference only
        logger.info("RLStop: no training data, using pre-trained models in %s", rlstop_out)
        rlstop_sweep(
            data_dir=data_dir, out_dir=rlstop_out, train_dir=rlstop_out,
            topics=topics, skip_train=True,
        )
    else:
        # Neither training data nor pre-trained models — write empty parquet and continue.
        # To enable RLStop: place CLEF2017_qrels.txt + docids/ in
        #   cascade_rc/baselines/rlstop_vendor/data/
        logger.warning(
            "RLStop skipped — training data not found at %s and no pre-trained "
            "models in %s. Writing empty results parquet.\n"
            "  To enable: place CLEF2017_qrels.txt and clef2017/docids/ in "
            "cascade_rc/baselines/rlstop_vendor/data/",
            _rlstop_qrels, rlstop_out,
        )
        rlstop_sweep(
            data_dir=data_dir, out_dir=rlstop_out, train_dir=rlstop_out,
            topics=topics, dry_run=True,
        )

    logger.info("Step baselines: all baselines complete")


# ---------------------------------------------------------------------------
# Step 6: Calibrate (Algorithm 1)
# ---------------------------------------------------------------------------

def _write_nmin_abstention(topic_id: str, artefact_dir: Path) -> None:
    """Write placeholder results parquet when a topic abstains at N_min check."""
    baseline_dir = artefact_dir / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "method": "cascade_rc",
            "topic_id": topic_id,
            "alpha": float(a),
            "fnr": float("nan"),
            "wss_95": float("nan"),
        }
        for a in [0.05, 0.10, 0.20]
    ]
    pd.DataFrame(rows).to_parquet(
        baseline_dir / "cascade_rc_results.parquet", index=False
    )


def step_calibrate(topic_id: str, parquet_path: Path, artefact_dir: Path) -> object:
    """Run CASCADE-RC calibration (Algorithm 1) to find certified θ̂.

    Performs an N_min compliance check (Theorem 5) before calibrating.
    Returns a 3-tuple (topic_id, "abstained", reason) if the check fails,
    in which case calibration is skipped and abstention is recorded.
    """
    from cascade_rc.calibration.main_calibrate import calibrate
    from cascade_rc.config import CascadeRCConfig
    from cascade_rc.evaluation.metrics import report_nmin_compliance

    df = pd.read_parquet(parquet_path)
    compliance = report_nmin_compliance(df, topic_id)
    logger.info(
        "Step calibrate: N_min check — topic=%s m+=%d N_min=%d margin=%d status=%s",
        topic_id,
        compliance["m_plus_conformal"],
        compliance["N_min"],
        compliance["margin"],
        compliance["status"],
    )

    if compliance["status"] == "ABSTAIN":
        reason = (
            f"m_plus_conformal={compliance['m_plus_conformal']} < "
            f"N_min={compliance['N_min']} (Theorem 5 not satisfied)"
        )
        logger.warning(
            "Step calibrate: ABSTAINING topic %s — %s. "
            "Skipping calibration; writing empty results parquet.",
            topic_id, reason,
        )
        _write_nmin_abstention(topic_id, artefact_dir)
        return (topic_id, "abstained", reason)

    cfg = CascadeRCConfig()
    logger.info("Step calibrate: running Algorithm 1 for %s …", topic_id)
    result = calibrate(
        topic_id=topic_id,
        calib_parquet=parquet_path,
        config=cfg,
        artefact_dir=artefact_dir,
    )

    if isinstance(result, tuple):
        logger.warning("Step calibrate: ABSTAINED — %s", result[2])
    else:
        logger.info(
            "Step calibrate: CERTIFIED — Λ̂=%d points, θ̂=%s",
            result.lambda_hat_mask.sum(), result.theta_hat.tolist(),
        )
    return result


# ---------------------------------------------------------------------------
# Step 7: Evaluate and export cascade_rc_results.parquet
# ---------------------------------------------------------------------------

def step_evaluate(topic_id: str, parquet_path: Path, artefact_dir: Path) -> pd.DataFrame:
    """Compute WSS/FNR metrics and export cascade_rc_results.parquet for figures."""
    from cascade_rc.certificates.store import CertificateStore
    from cascade_rc.evaluation.metrics import (
        evaluate_certificate, _derive_routing, _predictions_from_routing, _ensure_is_split,
        wss_at_recall,
    )
    from cascade_rc.config import CascadeRCConfig

    cfg = CascadeRCConfig()
    cert = CertificateStore.load(topic_id, artefact_dir)
    df = _ensure_is_split(pd.read_parquet(parquet_path))
    df_test = df[df["is_split"] == 2].reset_index(drop=True)

    routing_df = _derive_routing(df_test, cert.theta_hat)
    routing_dir = artefact_dir / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)
    routing_df[["pmid", "decision"]].to_parquet(
        routing_dir / f"{topic_id}.parquet", index=False,
    )

    # Full evaluation using the new metric suite (§9.3)
    alpha = float(cfg.ltt.alpha) if hasattr(cfg, "ltt") and hasattr(cfg.ltt, "alpha") else 0.10
    eval_result = evaluate_certificate(df, tuple(cert.theta_hat), alpha=alpha, B=5)

    # Write per-topic eval JSON to artefacts/cascade_rc/results/<topic>_eval.json
    results_dir = artefact_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    eval_path = results_dir / f"{topic_id}_eval.json"
    eval_path.write_text(json.dumps(eval_result, indent=2))
    logger.info(
        "Step evaluate: %s_eval.json written (WSS=%.4f, FNR=%.4f, cert_valid=%s)",
        topic_id, eval_result["wss_95"], eval_result["fnr_test"], eval_result["certificate_valid"],
    )

    # Build cascade_rc_results.parquet (consumed by figures.py)
    baseline_dir = artefact_dir / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    fnr = eval_result["fnr_test"]
    wss_95 = eval_result["wss_95"] if eval_result["wss_95"] != -999.0 else float("nan")
    rows = []
    for alpha_level in [0.05, 0.10, 0.20]:
        rows.append({
            "method": "cascade_rc",
            "topic_id": topic_id,
            "alpha": float(alpha_level),
            "fnr": fnr,
            "wss_95": wss_95,
        })

    crc_df = pd.DataFrame(rows)
    crc_df.to_parquet(baseline_dir / "cascade_rc_results.parquet", index=False)
    return crc_df


# ---------------------------------------------------------------------------
# Step 8: Generate figures
# ---------------------------------------------------------------------------

def step_figures(artefact_dir: Path) -> None:
    """Generate publication figures from baseline results."""
    from cascade_rc.evaluation.figures import gen_figures

    logger.info("Step figures: generating publication figures …")
    gen_figures(artefact_dir=artefact_dir)
    logger.info("Step figures: figures written to %s/figures/", artefact_dir)


# ---------------------------------------------------------------------------
# Task 3: Collect cross-topic results summary
# ---------------------------------------------------------------------------

def collect_results_summary(
    topics: list[str],
    out_dir: Path,
    artefact_dir: Path,
    topic_runtimes: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Collect per-topic metrics into artefacts/cascade_rc/results/all_topics_summary.parquet."""
    from cascade_rc.evaluation.metrics import (
        report_nmin_compliance, _ensure_is_split,
        _derive_routing, _predictions_from_routing, wss_at_recall,
    )
    from cascade_rc.certificates.store import CertificateStore

    B = 5  # LLM ensemble size (calls per abstract in uncertain band)
    rows = []

    for topic_id in topics:
        parquet_path = out_dir / f"{topic_id}.parquet"
        family = TOPIC_FAMILY.get(topic_id, "Unknown")
        runtime = (topic_runtimes or {}).get(topic_id, float("nan"))

        if not parquet_path.exists():
            logger.warning("collect_results: %s parquet not found, inserting NaN row", topic_id)
            rows.append(_nan_row(topic_id, family, "MISSING", runtime))
            continue

        df = _ensure_is_split(pd.read_parquet(parquet_path))
        compliance = report_nmin_compliance(df, topic_id)
        nmin_status = compliance["status"]
        m_plus_conformal = compliance["m_plus_conformal"]
        m_plus_test = compliance["m_plus_test"]

        try:
            cert = CertificateStore.load(topic_id, artefact_dir)
        except FileNotFoundError:
            logger.warning("collect_results: no certificate for %s, inserting NaN row", topic_id)
            rows.append({
                "topic_id": topic_id,
                "family": family,
                "m_plus_conformal": m_plus_conformal,
                "m_plus_test": m_plus_test,
                "nmin_status": nmin_status,
                "theta_hat_lambda_lo": float("nan"),
                "theta_hat_lambda_hi": float("nan"),
                "theta_hat_tau_SE": float("nan"),
                "lambda_hat_size": 0,
                "eta_lcb_star": float("nan"),
                "alpha_dagger": float("nan"),
                "wss_95": float("nan"),
                "fnr_test": float("nan"),
                "frac_cheap_reject": float("nan"),
                "frac_auto_include": float("nan"),
                "frac_llm_followed": float("nan"),
                "frac_human_review": float("nan"),
                "llm_calls_per_abstract": float("nan"),
                "runtime_seconds": runtime,
            })
            continue

        # θ̂ index for per-point scalar metrics
        match = np.where((cert.theta_grid == cert.theta_hat).all(axis=1))[0]
        theta_hat_idx = int(match[0]) if len(match) > 0 else 0
        eta_lcb_star = float(cert.eta_lcb_grid[theta_hat_idx])
        alpha_dagger_val = float(cert.alpha_dagger_grid[theta_hat_idx])
        lambda_hat_size = int(cert.lambda_hat_mask.sum())

        # Routing on test set
        df_test = df[df["is_split"] == 2].reset_index(drop=True)
        routing_df = _derive_routing(df_test, cert.theta_hat)
        decisions = routing_df["decision"].value_counts().to_dict()
        total_test = len(routing_df)

        n_cheap_reject = decisions.get("auto_reject", 0)
        n_auto_include = decisions.get("auto_accept", 0)
        n_llm_escalate = decisions.get("llm_escalate", 0)
        n_human_review = decisions.get("human_review", 0)
        n_llm_band = n_llm_escalate + n_human_review

        def _frac(n: int) -> float:
            return n / total_test if total_test > 0 else float("nan")

        frac_cheap_reject = _frac(n_cheap_reject)
        frac_auto_include = _frac(n_auto_include)
        frac_llm_followed = _frac(n_llm_escalate)
        frac_human_review_val = _frac(n_human_review)
        llm_calls_per_abstract = _frac(n_llm_band) * B

        # WSS@0.95 and FNR on test set
        predictions = _predictions_from_routing(routing_df)
        y_true = df_test["y_abstract"].to_numpy(dtype=np.int8)
        wss_result = wss_at_recall(predictions, y_true, target_recall=0.95)

        wss_95 = wss_result["wss"]
        achieved_recall = wss_result["achieved_recall"]
        fnr_test = (
            float(1.0 - achieved_recall)
            if not (isinstance(achieved_recall, float) and np.isnan(achieved_recall))
            else float("nan")
        )

        rows.append({
            "topic_id": topic_id,
            "family": family,
            "m_plus_conformal": m_plus_conformal,
            "m_plus_test": m_plus_test,
            "nmin_status": nmin_status,
            "theta_hat_lambda_lo": float(cert.theta_hat[0]),
            "theta_hat_lambda_hi": float(cert.theta_hat[1]),
            "theta_hat_tau_SE": float(cert.theta_hat[2]),
            "lambda_hat_size": lambda_hat_size,
            "eta_lcb_star": eta_lcb_star,
            "alpha_dagger": alpha_dagger_val,
            "wss_95": wss_95,
            "fnr_test": fnr_test,
            "frac_cheap_reject": frac_cheap_reject,
            "frac_auto_include": frac_auto_include,
            "frac_llm_followed": frac_llm_followed,
            "frac_human_review": frac_human_review_val,
            "llm_calls_per_abstract": llm_calls_per_abstract,
            "runtime_seconds": runtime,
        })

    df_summary = pd.DataFrame(rows)
    results_dir = artefact_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / "all_topics_summary.parquet"
    df_summary.to_parquet(out_path, index=False)
    logger.info("collect_results: summary written to %s (%d topics)", out_path, len(df_summary))
    return df_summary


def _nan_row(topic_id: str, family: str, nmin_status: str, runtime: float) -> dict:
    """Return a fully-NaN row for topics with missing artefacts."""
    return {
        "topic_id": topic_id,
        "family": family,
        "m_plus_conformal": 0,
        "m_plus_test": 0,
        "nmin_status": nmin_status,
        "theta_hat_lambda_lo": float("nan"),
        "theta_hat_lambda_hi": float("nan"),
        "theta_hat_tau_SE": float("nan"),
        "lambda_hat_size": 0,
        "eta_lcb_star": float("nan"),
        "alpha_dagger": float("nan"),
        "wss_95": float("nan"),
        "fnr_test": float("nan"),
        "frac_cheap_reject": float("nan"),
        "frac_auto_include": float("nan"),
        "frac_llm_followed": float("nan"),
        "frac_human_review": float("nan"),
        "llm_calls_per_abstract": float("nan"),
        "runtime_seconds": runtime,
    }


# ---------------------------------------------------------------------------
# Task 4: Validate cross-topic results
# ---------------------------------------------------------------------------

def validate_results(df_summary: pd.DataFrame, alpha: float = 0.10) -> None:
    """Validate per-topic results against Theorem 5 guarantees.

    Prints a validation report to stdout.
    Raises AssertionError (with traceback) if any certificate violation is found.

    Checks:
      1. fnr_test <= alpha for every PASS topic (Theorem 5 guarantee)
      2. theta_hat_tau_SE > 0.0 for every PASS topic (τ_SE bug fix confirmation)
      3. lambda_hat_size > 0 for every PASS topic (non-degenerate certificate)
      4. wss_95 > -0.20 for every topic (sanity floor)
    """
    print("\n" + "=" * 60)
    print("VALIDATION REPORT")
    print("=" * 60)

    n_pass = int((df_summary["nmin_status"] == "PASS").sum())
    n_abstain = int((df_summary["nmin_status"] == "ABSTAIN").sum())
    n_missing = int((df_summary["nmin_status"] == "MISSING").sum())
    print(f"Topics: {len(df_summary)} total | PASS={n_pass} | ABSTAIN={n_abstain} | MISSING={n_missing}")
    print()

    violations: list[str] = []
    warnings: list[str] = []

    for _, row in df_summary.iterrows():
        topic_id = str(row["topic_id"])
        nmin_status = str(row["nmin_status"])
        fnr = float(row["fnr_test"])
        tau_se = float(row["theta_hat_tau_SE"])
        lambda_hat_size = int(row["lambda_hat_size"])
        wss = float(row["wss_95"])

        is_pass = nmin_status == "PASS"
        fnr_str = f"{fnr:.4f}" if not np.isnan(fnr) else "NaN"
        tau_str = f"{tau_se:.4f}" if not np.isnan(tau_se) else "NaN"
        wss_str = f"{wss:.4f}" if not np.isnan(wss) else "NaN"
        status_tag = f"[{nmin_status}]"

        print(f"  {topic_id}  fnr={fnr_str}  τ_SE={tau_str}  Λ̂={lambda_hat_size}  WSS={wss_str}  {status_tag}")

        if is_pass:
            # Check 1: certificate recall guarantee
            if not np.isnan(fnr) and fnr > alpha:
                violations.append(
                    f"{topic_id}: fnr_test={fnr:.4f} > alpha={alpha} [CERTIFICATE VIOLATION]"
                )
            # Check 2: τ_SE bug fix
            if not np.isnan(tau_se) and tau_se == 0.0:
                violations.append(
                    f"{topic_id}: theta_hat_tau_SE=0.0 [τ_SE bug not fixed — degenerate θ̂]"
                )
            # Check 3: non-degenerate certificate
            if lambda_hat_size == 0:
                violations.append(
                    f"{topic_id}: lambda_hat_size=0 [degenerate certificate — empty Λ̂]"
                )

        # Check 4: WSS sanity floor (all topics, not just PASS)
        if not np.isnan(wss) and wss <= -0.20:
            warnings.append(f"{topic_id}: wss_95={wss:.4f} ≤ -0.20 [below sanity floor]")

    print()
    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  ! {w}")
        print()

    if violations:
        print("VIOLATIONS:")
        for v in violations:
            print(f"  ✗ {v}")
        print("=" * 60)
        raise AssertionError(
            f"{len(violations)} validation violation(s) found:\n" + "\n".join(violations)
        )

    print("All checks PASSED.")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Task 5: Cross-topic statistics
# ---------------------------------------------------------------------------

def compute_cross_topic_stats(df_summary: pd.DataFrame, artefact_dir: Path) -> dict:
    """Compute and print cross-topic statistics; append to cross_topic_stats.json."""
    from datetime import datetime, timezone

    pass_df = df_summary[df_summary["nmin_status"] == "PASS"]
    wss_vals = pass_df["wss_95"].dropna()
    fnr_vals = pass_df["fnr_test"].dropna()
    abstention_rate = float((df_summary["nmin_status"] == "ABSTAIN").mean())

    def _safe_mean(s: pd.Series) -> float:
        return float(s.mean()) if len(s) > 0 else float("nan")

    def _safe_std(s: pd.Series) -> float:
        return float(s.std()) if len(s) > 1 else float("nan")

    stats = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_topics": int(len(df_summary)),
        "n_pass": int((df_summary["nmin_status"] == "PASS").sum()),
        "n_abstain": int((df_summary["nmin_status"] == "ABSTAIN").sum()),
        "mean_wss_95": _safe_mean(wss_vals),
        "std_wss_95": _safe_std(wss_vals),
        "mean_fnr": _safe_mean(fnr_vals),
        "std_fnr": _safe_std(fnr_vals),
        "mean_abstention_rate": abstention_rate,
    }

    print("\n" + "=" * 60)
    print("CROSS-TOPIC STATISTICS")
    print("=" * 60)
    print(f"  n_topics           = {stats['n_topics']}")
    print(f"  n_pass             = {stats['n_pass']}")
    print(f"  n_abstain          = {stats['n_abstain']}")
    print(f"  mean_wss_95        = {stats['mean_wss_95']:.4f}")
    print(f"  std_wss_95         = {stats['std_wss_95']:.4f}")
    print(f"  mean_fnr           = {stats['mean_fnr']:.4f}")
    print(f"  std_fnr            = {stats['std_fnr']:.4f}")
    print(f"  mean_abstention_rate = {stats['mean_abstention_rate']:.4f}")
    print("=" * 60)

    results_dir = artefact_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stats_path = results_dir / "cross_topic_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2))
    logger.info("cross_topic_stats written to %s", stats_path)

    return stats


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(
    topic_id: str,
    *,
    data_dir: Path | None = None,
    out_dir: Path | None = None,
    cache_path: Path | None = None,
    skip_llm: bool = False,
    resume_from: str | None = None,
    force_resplit: bool = False,
    steps: list[str] | None = None,
    resume: bool = False,
) -> float:
    """Run the full CASCADE-RC pipeline for one topic.

    Returns:
        Wall-clock runtime in seconds.
    """
    t0 = time.monotonic()

    if data_dir is None:
        from cascade_rc.data.clef_tar_loader import _DEFAULT_CACHE_DIR
        data_dir = _DEFAULT_CACHE_DIR
    if out_dir is None:
        out_dir = Path("artefacts/cascade_rc/data")
    if cache_path is None:
        cache_path = Path("artefacts/cascade_rc/llm_cache") / f"llm_cache_{topic_id}.db"

    artefact_dir = Path("artefacts/cascade_rc")
    parquet_path = out_dir / f"{topic_id}.parquet"

    if force_resplit:
        if parquet_path.exists():
            step_resplit(topic_id, parquet_path)
        else:
            logger.warning("[resplit] Parquet not found at %s — skipping resplit", parquet_path)

    # Determine which steps to execute
    if steps is not None:
        steps_to_run = [s for s in STEPS if s in steps]  # preserve canonical order
    else:
        steps_to_run = STEPS[:]

    if resume_from:
        if resume_from not in STEPS:
            raise ValueError(f"Unknown resume step: {resume_from}. Valid: {STEPS}")
        idx = STEPS.index(resume_from)
        steps_to_run = [s for s in steps_to_run if STEPS.index(s) >= idx]

    if skip_llm:
        steps_to_run = [s for s in steps_to_run if s not in ("score_u", "merge_u")]

    step_fns = {
        "ingest": lambda: step_ingest(topic_id, data_dir, out_dir),
        "score_s": lambda: step_score_s(topic_id, parquet_path, data_dir),
        "score_u": lambda: step_score_u(topic_id, parquet_path, cache_path),
        "merge_u": lambda: step_merge_u(topic_id, parquet_path, cache_path),
        "baselines": lambda: step_baselines(topic_id, out_dir, artefact_dir / "baselines"),
        "calibrate": lambda: step_calibrate(topic_id, parquet_path, artefact_dir),
        "evaluate": lambda: step_evaluate(topic_id, parquet_path, artefact_dir),
        "figures": lambda: step_figures(artefact_dir),
    }

    n_steps = len(steps_to_run)
    _progress_print(f"\n{'='*60}")
    _progress_print(f"  CASCADE-RC | topic: {topic_id} | steps: {n_steps}")
    _progress_print(f"{'='*60}")

    for i, step_name in enumerate(steps_to_run, 1):
        step_label = f"[{i}/{n_steps}] {step_name:<12}"

        if resume and _step_is_done(step_name, topic_id, out_dir, artefact_dir):
            logger.info("Step %s: SKIPPED (--resume, artefacts already exist)", step_name)
            _progress_print(f"  {step_label}  SKIPPED")
            continue

        _progress_print(f"  {step_label}  running ...", end="")
        t_step = time.monotonic()
        step_fns[step_name]()
        step_elapsed = time.monotonic() - t_step
        _progress_print(f"\r  {step_label}  DONE  ({step_elapsed:.1f}s)")
        logger.info("Step %s: DONE (%.1fs)", step_name, step_elapsed)

    elapsed = time.monotonic() - t0
    _progress_print(f"{'='*60}")
    _progress_print(f"  {topic_id} complete | total: {elapsed:.1f}s")
    _progress_print(f"{'='*60}\n")
    logger.info("Pipeline complete for topic %s (%.1fs)", topic_id, elapsed)
    return elapsed


def run_pipeline_for_topic(
    topic_id: str,
    config: "CascadeRCConfig",
    steps: list[str] | None = None,
    out_dir: Path | None = None,
    resume: bool = False,
) -> float:
    """Run all pipeline steps for one topic. Subprocess-safe — no shared state.

    Derives the per-topic SQLite cache path from config.artefact_dir so each
    subprocess writes to its own file and never contends with siblings.

    Returns:
        Wall-clock runtime in seconds.
    """
    if out_dir is None:
        out_dir = config.artefact_dir / "data"
    cache_path = config.artefact_dir / "llm_cache" / f"llm_cache_{topic_id}.db"
    return run_pipeline(
        topic_id=topic_id,
        out_dir=out_dir,
        cache_path=cache_path,
        steps=steps,
        resume=resume,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="CASCADE-RC end-to-end pipeline orchestrator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", default=None,
                        help="Single topic ID, e.g. CD008874 (use --topics for multi-topic runs)")
    parser.add_argument("--topics", nargs="+", default=None, metavar="TOPIC_ID",
                        help="One or more topic IDs for a multi-topic run")
    parser.add_argument("--steps", nargs="+", choices=STEPS, default=None, metavar="STEP",
                        help=f"Explicit list of steps to run (subset of: {STEPS}); default: all")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="CLEF-TAR data directory")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Output directory for parquets (default: artefacts/cascade_rc/data)")
    parser.add_argument("--cache-path", type=Path, default=None,
                        help="Path to SQLite LLM cache (default: artefacts/cascade_rc/llm_cache/llm_cache_{topic_id}.db)")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Skip LLM scoring (use s==u placeholder)")
    parser.add_argument("--resume-from", choices=STEPS, default=None,
                        help="Resume pipeline starting from this step (skips all earlier steps)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip any step whose output artefacts already exist")
    parser.add_argument("--force-resplit", action="store_true",
                        help="Apply three-way split to existing parquet before running steps")
    parser.add_argument("--collect-summary", action="store_true",
                        help="After topic runs: collect summary parquet, validate, compute cross-topic stats")
    parser.add_argument(
        "--validate-nmin", action="store_true",
        help=(
            "Check N_min compliance for all six topics, print table, "
            "exit 0 if all pass or 1 if any abstain"
        ),
    )
    args = parser.parse_args()

    if args.validate_nmin:
        from cascade_rc.evaluation.metrics import (
            report_nmin_compliance,
            build_nmin_compliance_table,
            _print_compliance_table,
        )

        out_dir = args.out_dir or Path("artefacts/cascade_rc/data")
        results = []
        for topic_id in DEFAULT_TOPICS:
            parquet_path = out_dir / f"{topic_id}.parquet"
            if not parquet_path.exists():
                print(
                    f"WARNING: {parquet_path} not found — skipping {topic_id}",
                    file=sys.stderr,
                )
                continue
            df_topic = pd.read_parquet(parquet_path)
            result = report_nmin_compliance(df_topic, topic_id)
            results.append(result)

        if not results:
            print("No topic parquets found under %s. Run ingest first." % out_dir,
                  file=sys.stderr)
            sys.exit(1)

        table = build_nmin_compliance_table(results)
        _print_compliance_table(table)

        any_abstain = any(r["status"] == "ABSTAIN" for r in results)
        sys.exit(1 if any_abstain else 0)

    # Resolve topic list (--topics takes priority over --topic)
    if args.topics:
        topic_ids = args.topics
    elif args.topic:
        topic_ids = [args.topic]
    else:
        parser.error("--topic or --topics is required unless --validate-nmin is specified")

    out_dir = args.out_dir or Path("artefacts/cascade_rc/data")
    artefact_dir = Path("artefacts/cascade_rc")
    topic_runtimes: dict[str, float] = {}

    n_topics = len(topic_ids)
    if n_topics > 1:
        _progress_print(f"\nCASCADE-RC: {n_topics} topics queued: {' '.join(topic_ids)}")

    for t_idx, topic_id in enumerate(topic_ids, 1):
        if n_topics > 1:
            _progress_print(f"\n>>> Topic {t_idx}/{n_topics}: {topic_id}")
        runtime = run_pipeline(
            topic_id=topic_id,
            data_dir=args.data_dir,
            out_dir=out_dir,
            cache_path=args.cache_path,
            skip_llm=args.skip_llm,
            resume_from=args.resume_from,
            force_resplit=args.force_resplit,
            steps=args.steps,
            resume=args.resume,
        )
        topic_runtimes[topic_id] = runtime

    if args.collect_summary:
        logger.info("Running post-pipeline collection (Tasks 3–5) …")
        df_summary = collect_results_summary(topic_ids, out_dir, artefact_dir, topic_runtimes)
        validate_results(df_summary)
        compute_cross_topic_stats(df_summary, artefact_dir)


if __name__ == "__main__":
    main()