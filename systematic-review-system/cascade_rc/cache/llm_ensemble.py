"""
cascade_rc/cache/llm_ensemble.py
===================================
B=5 stochastic ensemble over the Tier-2 abstract screening prompt.

Each call uses the existing abstract_screening.txt prompt with temperature=0.7
so individual predictions are stochastic.  Voting logic:

  - "Uncertain" votes are excluded from the Include / Exclude competition.
  - If Include > Exclude → majority = "Include",   u = include_count / B
  - If Exclude > Include → majority = "Exclude",   u = exclude_count / B
  - Tie (or all Uncertain) → majority = "Uncertain", u = 0.0  (hardcoded)

This ensures the self-consistency gate (τ_SE) fails for ambiguous abstracts,
routing them to the human-recovery branch (CASCADE-RC paper §4, eq. 2).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, Optional

from infrastructure.llm_client import LLMClient
from tier2_screening.abstract_screener import _TEMPLATE, _fill_template

logger = logging.getLogger(__name__)

Vote = Literal["Include", "Exclude", "Uncertain"]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EnsembleResult:
    votes:    list[Vote]
    majority: Vote
    u:        float   # self-consistency score ∈ [0, 1]
    y_hat:    int     # 1 if majority == "Include" else 0


# ---------------------------------------------------------------------------
# Voting helpers
# ---------------------------------------------------------------------------

def _parse_vote(parsed_json: Any) -> Vote:
    """Map a parsed LLM JSON response to a vote label."""
    if not isinstance(parsed_json, dict):
        return "Uncertain"
    satisfies = parsed_json.get("satisfies", "uncertain")
    if satisfies is True or satisfies == "true":
        return "Include"
    if satisfies is False or satisfies == "false":
        return "Exclude"
    return "Uncertain"


def _vote_to_int(vote: Vote) -> int:
    """Map Vote label to integer: Include→1, Exclude→0, Uncertain→2."""
    if vote == "Include":
        return 1
    if vote == "Uncertain":
        return 2
    return 0


def _int_to_vote(v: int) -> Vote:
    """Map integer back to Vote label: 1→Include, 0→Exclude, 2→Uncertain."""
    if v == 1:
        return "Include"
    if v == 2:
        return "Uncertain"
    return "Exclude"


def _majority_and_u(votes: list[Vote], n: int) -> tuple[Vote, float, int]:
    """
    Compute majority label, self-consistency score u, and y_hat.

    Uncertain votes are excluded from the Include/Exclude binary competition.
    A tie (or all-Uncertain) resolves to majority='Uncertain', u=0.0, y_hat=0,
    which causes u < τ_SE and routes the abstract to human review.

    Returns (majority, u, y_hat).
    """
    assert len(votes) == n, f"votes length {len(votes)} != n {n}"
    include_count = votes.count("Include")
    exclude_count = votes.count("Exclude")

    if include_count > exclude_count:
        majority: Vote = "Include"
    elif exclude_count > include_count:
        majority = "Exclude"
    else:
        majority = "Uncertain"

    if majority == "Uncertain":
        return "Uncertain", 0.0, 0

    majority_count = include_count if majority == "Include" else exclude_count
    y_hat = 1 if majority == "Include" else 0
    return majority, majority_count / n, y_hat


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a precise systematic review screener. "
    "Reply only with the requested JSON."
)

_CRITERION_TEXT = (
    "The study satisfies all PICO eligibility criteria for this systematic review."
)


async def screen_abstract_ensemble(
    title: str,
    abstract: str,
    pico: dict,
    pmid: str | None = None,
    n_calls: int = 5,
    temperature: float = 0.7,
    _client: Optional[Any] = None,
    _cache: Optional[Any] = None,
    _model_id: str = "gpt-oss:120b",
    _template_v: str = "v1",
) -> EnsembleResult:
    """
    Run B=n_calls stochastic screenings of one abstract and aggregate the votes.

    When pmid and _cache are both provided, each slot is looked up in the SQLite
    cache before calling the LLM. The sequential per-slot loop (replacing the former
    asyncio.gather) enables crash-resumable runs: a killed process costs zero extra
    LLM calls on restart for completed slots.

    Parameters
    ----------
    pmid : str | None
        PMID for cache keying. None disables caching (backwards-compatible).
    _cache : SQLiteEnsembleCache | None
        Injected cache instance. None disables caching.
    _model_id : str
        Model identifier stored in cache rows (default gpt-oss:120b).
    _template_v : str
        Template version tag for ablation filtering (default v1).
    """
    client = _client if _client is not None else LLMClient()

    pico_text = (
        f"Population: {pico.get('population', '')}\n"
        f"Intervention: {pico.get('intervention', '')}\n"
        f"Comparator: {pico.get('comparator', '')}\n"
        f"Outcome: {pico.get('outcome', '')}\n"
        f"Study design: {pico.get('study_design', '')}"
    )

    prompt = _fill_template(
        _TEMPLATE,
        pico_text=pico_text,
        criterion_text=_CRITERION_TEXT,
        title=title,
        abstract=str(abstract)[:500],
    )
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()

    use_cache = _cache is not None and pmid is not None
    votes: list[Vote] = []

    for b in range(n_calls):
        cached = None
        if use_cache:
            cached = _cache.get(
                model_id=_model_id,
                prompt_sha=prompt_sha,
                pmid=pmid,
                temperature=temperature,
                seed_b=b,
                template_v=_template_v,
            )

        if cached is not None:
            vote: Vote = cached["vote_label"]  # type: ignore[assignment]
            logger.info("cache_hit pmid=%s slot=%d", pmid, b)
        else:
            response = await client.complete(
                prompt=prompt,
                system=_SYSTEM,
                model=_model_id,
                temperature=temperature,
                max_tokens=128,
                response_format="json",
            )
            vote = _parse_vote(response.parsed_json)
            if use_cache:
                _cache.put(
                    model_id=_model_id,
                    prompt_sha=prompt_sha,
                    pmid=pmid,
                    temperature=temperature,
                    seed_b=b,
                    template_v=_template_v,
                    response=response.parsed_json or {},
                    verdict=_vote_to_int(vote),
                    vote_label=vote,
                )
            if use_cache:
                logger.info("cache_miss pmid=%s slot=%d vote=%s", pmid, b, vote)

        votes.append(vote)

    majority, u, y_hat = _majority_and_u(votes, n_calls)
    logger.debug("Ensemble: votes=%s majority=%s u=%.3f", votes, majority, u)
    return EnsembleResult(votes=votes, majority=majority, u=u, y_hat=y_hat)


# ---------------------------------------------------------------------------
# Offline driver — populate cache for an entire CLEF-TAR topic
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import argparse
    import json
    import sys
    from pathlib import Path as _Path

    try:
        from tqdm import tqdm as _tqdm
    except ImportError:
        def _tqdm(it, **_):  # type: ignore[misc]
            return it

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(name)s %(message)s")
    _driver_log = _logging.getLogger("cascade_rc.cache.llm_ensemble.__main__")

    from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache as _Cache
    from cascade_rc.config import CascadeRCConfig as _Cfg
    from cascade_rc.data.clef_tar_loader import (
        _DEFAULT_CACHE_DIR as _TAR_DIR,
        download_clef_tar_2019 as _download,
        load_topic as _load_topic,
    )
    from cascade_rc.data.pubmed_fetch import fetch_abstracts as _fetch

    _ap = argparse.ArgumentParser(
        description="Populate LLM ensemble cache for a CLEF-TAR topic."
    )
    _ap.add_argument("--topic", required=True, help="CLEF-TAR topic ID, e.g. CD012768")
    _ap.add_argument("--B", type=int, default=5, help="Ensemble size (default 5)")
    _ap.add_argument("--T", type=float, default=0.7, help="LLM temperature (default 0.7)")
    _ap.add_argument("--cache-path", type=_Path, default=None, help="Path to SQLite cache DB")
    _ap.add_argument("--template-v", default="v1", help="Template version tag")
    _ap.add_argument("--ncbi-email", default="", help="Email for NCBI API (required by NCBI ToS)")
    _ap.add_argument("--max-failures", type=int, default=10,
                     help="Abort after N consecutive PMID failures (default 10)")
    _ap.add_argument("--resume-from-pmid", default=None,
                     help="Skip PMIDs before this one in the candidate list")
    _ap.add_argument("--dry-run", action="store_true",
                     help="Report cache hit rate without making LLM calls, then exit")
    _args = _ap.parse_args()

    _cfg = _Cfg()
    _cache_path: _Path = _args.cache_path or _cfg.sqlite_cache_path
    _ncbi_email: str = _args.ncbi_email or _cfg.ncbi_email
    if not _ncbi_email:
        _driver_log.warning("No NCBI email provided; NCBI may throttle requests.")

    # Download CLEF-TAR data if not cached
    if not (_TAR_DIR / "2019-TAR").exists():
        _driver_log.info("Downloading CLEF-TAR data to %s …", _TAR_DIR)
        _download(_TAR_DIR)

    _topic = _load_topic(_args.topic, _TAR_DIR)
    _pmids: list[str] = _topic.candidate_pmids

    # Apply --resume-from-pmid
    if _args.resume_from_pmid is not None:
        try:
            _resume_idx = _pmids.index(_args.resume_from_pmid)
            _pmids = _pmids[_resume_idx:]
            _driver_log.info(
                "Resuming from PMID %s (skipping first %d)", _args.resume_from_pmid, _resume_idx
            )
        except ValueError:
            _driver_log.error(
                "--resume-from-pmid %s not found in topic candidate list", _args.resume_from_pmid
            )
            sys.exit(1)

    # Fetch abstracts via PubMed (per-PMID JSON cache in artefacts/)
    _driver_log.info("Fetching abstracts for %d PMIDs …", len(_pmids))
    _abstracts: dict = asyncio.run(
        _fetch(_pmids, email=_ncbi_email, api_key=_cfg.ncbi_api_key)
    )

    _valid_pmids = [
        p for p in _pmids
        if p in _abstracts and _abstracts[p].get("abstract")
    ]
    _skipped = len(_pmids) - len(_valid_pmids)
    if _skipped:
        _driver_log.warning("Skipping %d PMIDs with no abstract", _skipped)

    _cache = _Cache(_cache_path)
    _pico: dict = {
        "population": "", "intervention": "", "comparator": "", "outcome": "", "study_design": ""
    }

    # --dry-run: report cache completeness per PMID, exit without LLM calls
    if _args.dry_run:
        _hits = 0
        for _p in _valid_pmids:
            _rec = _abstracts[_p]
            _pico_text = (
                f"Population: \nIntervention: \nComparator: \n"
                f"Outcome: \nStudy design: "
            )
            _prompt = _fill_template(
                _TEMPLATE,
                pico_text=_pico_text,
                criterion_text=_CRITERION_TEXT,
                title=str(_rec.get("title", "")),
                abstract=str(_rec.get("abstract", ""))[:500],
            )
            _sha = hashlib.sha256(_prompt.encode()).hexdigest()
            _rows = _cache.fetch_ensemble(
                model_id=LLMClient.GPT_MODEL,
                prompt_sha=_sha,
                pmid=_p,
                temperature=_args.T,
                template_v=_args.template_v,
                B=_args.B,
            )
            if len(_rows) == _args.B:
                _hits += 1
        print(json.dumps({
            "topic": _args.topic,
            "total_valid_pmids": len(_valid_pmids),
            "fully_cached": _hits,
            "cache_hit_rate": _hits / len(_valid_pmids) if _valid_pmids else 0.0,
            "would_call_llm": (len(_valid_pmids) - _hits) * _args.B,
        }, indent=2))
        _cache.close()
        sys.exit(0)

    # Main loop
    _client = LLMClient()
    _failure_count = 0

    for _pmid in _tqdm(_valid_pmids, desc=f"Ensemble {_args.topic}"):
        _rec = _abstracts[_pmid]
        try:
            asyncio.run(
                screen_abstract_ensemble(
                    title=str(_rec.get("title", "")),
                    abstract=str(_rec.get("abstract", "")),
                    pico=_pico,
                    pmid=_pmid,
                    n_calls=_args.B,
                    temperature=_args.T,
                    _client=_client,
                    _cache=_cache,
                    _model_id=LLMClient.GPT_MODEL,
                    _template_v=_args.template_v,
                )
            )
            _failure_count = 0
        except sqlite3.Error as exc:
            _driver_log.error("PMID %s: structural cache error — aborting: %s", _pmid, exc)
            _cache.close()
            sys.exit(2)
        except Exception as exc:  # noqa: BLE001
            _failure_count += 1
            _driver_log.warning(
                "PMID %s: transient failure %d/%d: %s",
                _pmid, _failure_count, _args.max_failures, exc,
            )
            if _failure_count >= _args.max_failures:
                _driver_log.error(
                    "Aborting: %d consecutive failures exceeded --max-failures=%d",
                    _failure_count, _args.max_failures,
                )
                _cache.close()
                sys.exit(1)

    print(json.dumps(_cache.stats(), indent=2))
    _cache.close()
