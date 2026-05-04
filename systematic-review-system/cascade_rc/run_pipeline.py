"""End-to-end orchestrator for CASCADE-RC systematic review pipeline.

Chains all steps from data ingestion to figure generation for a single topic.

Usage:
    python -m cascade_rc.run_pipeline --topic CD008874
    python -m cascade_rc.run_pipeline --topic CD008874 --skip-llm  # use cached s==u
    python -m cascade_rc.run_pipeline --topic CD008874 --resume-from calibrate
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]

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
    if "s" in df.columns and (df["s"] > 0.0).sum() > 0:
        logger.info("Step score_s: s column already populated, skipping")
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
    import asyncio
    import sqlite3

    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble
    from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache
    from cascade_rc.config import CascadeRCConfig
    from infrastructure.llm_client import LLMClient
    from tier2_screening.abstract_screener import _TEMPLATE, _fill_template

    df = pd.read_parquet(parquet_path)
    cfg = CascadeRCConfig()
    cache = SQLiteEnsembleCache(cache_path)

    pmids = df["pmid"].tolist()
    abstracts: dict[str, dict] = {}
    for _, row in df.iterrows():
        pmid = str(row["pmid"])
        abstracts[pmid] = {
            "title": str(row.get("title", "")),
            "abstract": str(row.get("abstract", "")),
        }

    pico: dict = {
        "population": "", "intervention": "", "comparator": "",
        "outcome": "", "study_design": "",
    }

    client = LLMClient()
    failure_count = 0

    for pmid in pmids:
        rec = abstracts[pmid]
        if not rec.get("abstract"):
            continue

        try:
            asyncio.run(
                screen_abstract_ensemble(
                    title=rec["title"],
                    abstract=rec["abstract"],
                    pico=pico,
                    pmid=pmid,
                    n_calls=n_calls,
                    temperature=temperature,
                    _client=client,
                    _cache=cache,
                    _model_id=LLMClient.GPT_MODEL,
                    _template_v="v1",
                )
            )
            failure_count = 0
        except sqlite3.Error as exc:
            logger.error("PMID %s: structural cache error — aborting: %s", pmid, exc)
            cache.close()
            sys.exit(2)
        except Exception as exc:
            failure_count += 1
            logger.warning(
                "PMID %s: transient failure %d/%d: %s",
                pmid, failure_count, max_failures, exc,
            )
            if failure_count >= max_failures:
                logger.error(
                    "Aborting: %d consecutive failures exceeded max_failures=%d",
                    failure_count, max_failures,
                )
                cache.close()
                sys.exit(1)

    stats = cache.stats()
    logger.info("Step score_u: cache stats = %s", json.dumps(stats))
    cache.close()


# ---------------------------------------------------------------------------
# Step 4: Merge u scores from SQLite into parquet
# ---------------------------------------------------------------------------

def step_merge_u(topic_id: str, parquet_path: Path, cache_path: Path) -> pd.DataFrame:
    """Read LLM ensemble votes from SQLite, compute u per PMID, write to parquet."""
    import hashlib

    from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache
    from cascade_rc.cache.llm_ensemble import _majority_and_u, _parse_vote, Vote
    from infrastructure.llm_client import LLMClient
    from tier2_screening.abstract_screener import _TEMPLATE, _fill_template

    df = pd.read_parquet(parquet_path)
    cache = SQLiteEnsembleCache(cache_path)

    u_map: dict[str, float] = {}
    y_hat_map: dict[str, int] = {}

    for _, row in df.iterrows():
        pmid = str(row["pmid"])
        title = str(row.get("title", ""))
        abstract = str(row.get("abstract", ""))

        pico_text = (
            f"Population: \nIntervention: \nComparator: \nOutcome: \nStudy design: "
        )
        prompt = _fill_template(
            _TEMPLATE,
            pico_text=pico_text,
            criterion_text="The study satisfies all PICO eligibility criteria for this systematic review.",
            title=title,
            abstract=abstract[:500],
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
            votes: list[Vote] = [r["vote_label"] for r in rows_cached]
            majority, u, y_hat = _majority_and_u(votes, 5)
            u_map[pmid] = u
            y_hat_map[pmid] = y_hat
        else:
            logger.warning("PMID %s: only %d/5 cache rows found, keeping u=s", pmid, len(rows_cached))

    cache.close()

    if u_map:
        df["u"] = df["pmid"].astype(str).map(u_map).fillna(df["s"]).astype("float64")
        df["llm_y_hat"] = df["pmid"].astype(str).map(y_hat_map).fillna(0).astype("int64")
        df.to_parquet(parquet_path, index=False)
        logger.info("Step merge_u: updated u for %d PMIDs in %s", len(u_map), parquet_path)
    else:
        logger.warning("Step merge_u: no LLM scores found in cache; u remains equal to s")

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
    rlstop_sweep(
        data_dir=data_dir, out_dir=rlstop_out, train_dir=rlstop_out,
        topics=topics, skip_train=False,
    )

    logger.info("Step baselines: all baselines complete")


# ---------------------------------------------------------------------------
# Step 6: Calibrate (Algorithm 1)
# ---------------------------------------------------------------------------

def step_calibrate(topic_id: str, parquet_path: Path, artefact_dir: Path) -> object:
    """Run CASCADE-RC calibration (Algorithm 1) to find certified θ̂."""
    from cascade_rc.calibration.main_calibrate import calibrate
    from cascade_rc.config import CascadeRCConfig

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
    from cascade_rc.evaluation.metrics import wss_at_recall, _derive_routing, _predictions_from_routing

    cert = CertificateStore.load(topic_id, artefact_dir)
    df = pd.read_parquet(parquet_path)
    df_test = df[df["is_calib"] == 0].reset_index(drop=True)

    routing_df = _derive_routing(df_test, cert.theta_hat)
    routing_dir = artefact_dir / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)
    routing_df[["pmid", "decision"]].to_parquet(
        routing_dir / f"{topic_id}.parquet", index=False,
    )

    predictions = _predictions_from_routing(routing_df)
    y_true = df_test["y_abstract"].to_numpy(dtype=np.int8)
    wss_result = wss_at_recall(predictions, y_true, target_recall=0.95)

    # Compute FNR
    n_relevant = int(np.sum(y_true == 1))
    fnr = float(1.0 - wss_result["achieved_recall"]) if n_relevant > 0 else float("nan")

    # Build cascade_rc_results.parquet (consumed by figures.py)
    baseline_dir = artefact_dir / "baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for alpha_level in [0.05, 0.10, 0.20]:
        rows.append({
            "method": "cascade_rc",
            "topic_id": topic_id,
            "alpha": float(alpha_level),
            "fnr": fnr,
            "wss_95": wss_result["wss"] if wss_result["wss"] == wss_result["wss"] else float("nan"),
        })

    crc_df = pd.DataFrame(rows)
    crc_df.to_parquet(baseline_dir / "cascade_rc_results.parquet", index=False)
    logger.info(
        "Step evaluate: cascade_rc_results.parquet written (WSS=%.4f, FNR=%.4f)",
        wss_result["wss"], fnr,
    )
    return crc_df


# ---------------------------------------------------------------------------
# Step 8: Generate figures
# ---------------------------------------------------------------------------

def step_figures(artefact_dir: Path) -> None:
    """Generate publication figures from baseline results."""
    from cascade_rc.evaluation.figures import main as gen_figures

    logger.info("Step figures: generating publication figures …")
    gen_figures(artefact_dir=artefact_dir)
    logger.info("Step figures: figures written to %s/figures/", artefact_dir)


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
) -> None:
    """Run the full CASCADE-RC pipeline for one topic."""
    if data_dir is None:
        from cascade_rc.data.clef_tar_loader import _DEFAULT_CACHE_DIR
        data_dir = _DEFAULT_CACHE_DIR
    if out_dir is None:
        out_dir = Path("artefacts/cascade_rc/data")
    if cache_path is None:
        cache_path = Path("artefacts/cascade_rc/llm_cache.db")

    artefact_dir = Path("artefacts/cascade_rc")
    parquet_path = out_dir / f"{topic_id}.parquet"

    steps_to_run = STEPS[:]
    if resume_from:
        if resume_from not in STEPS:
            raise ValueError(f"Unknown resume step: {resume_from}. Valid: {STEPS}")
        idx = STEPS.index(resume_from)
        steps_to_run = STEPS[idx:]

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

    for step_name in steps_to_run:
        logger.info("=" * 60)
        logger.info("Pipeline step: %s (%d/%d)", step_name,
                     STEPS.index(step_name) + 1, len(STEPS))
        logger.info("=" * 60)
        step_fns[step_name]()
        logger.info("Step %s: DONE", step_name)

    logger.info("=" * 60)
    logger.info("Pipeline complete for topic %s", topic_id)
    logger.info("=" * 60)


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
    parser.add_argument("--topic", required=True, help="Topic ID, e.g. CD008874")
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="CLEF-TAR data directory")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="Output directory for parquets (default: artefacts/cascade_rc/data)")
    parser.add_argument("--cache-path", type=Path, default=None,
                        help="Path to SQLite LLM cache")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Skip LLM scoring (use s==u placeholder)")
    parser.add_argument("--resume-from", choices=STEPS, default=None,
                        help="Resume pipeline from this step")
    args = parser.parse_args()

    run_pipeline(
        topic_id=args.topic,
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        cache_path=args.cache_path,
        skip_llm=args.skip_llm,
        resume_from=args.resume_from,
    )


if __name__ == "__main__":
    main()
