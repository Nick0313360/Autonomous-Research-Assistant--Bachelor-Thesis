"""
cascade_rc/data/update_parquet.py
==================================
Enrich topic parquets with 's' and 'u' score columns produced by the
Tier-2 hybrid BM25+SPECTER2 ranker.

  s  — raw RRF score from HybridRetriever (relevance signal)
  u  — same as s (placeholder; replace with LLM confidence when available)

The mapping is: raw_score → s, s → u.  Both SCRC and Calibration consume
these columns; the SCRC abstain-rate quantile on u degrades to score-based
abstention when u == s, which is a valid and reproducible baseline.

Usage:
    python -m cascade_rc.data.update_parquet --topic CD008874
    python -m cascade_rc.data.update_parquet --topics CD008874 CD012080
    python -m cascade_rc.data.update_parquet            # all six topics
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Any

import pandas as pd

logger = logging.getLogger(__name__)


def add_scores_to_parquet(
    parquet_path: Path,
    query: str,
    _encoder: Optional[Any] = None,
) -> pd.DataFrame:
    """Add 's' and 'u' columns to an existing topic parquet, in place.

    Reads *parquet_path*, runs the hybrid ranker via compute_raw_scores(),
    merges ``raw_score`` back as ``s`` (and ``u``), then overwrites the file.

    Parameters
    ----------
    parquet_path:
        Path to an existing topic parquet with at least
        ``[pmid, title, abstract, y_abstract]``.
    query:
        Review query string forwarded to compute_raw_scores().
    _encoder:
        Optional injected SharedEncoderService (used in tests to avoid
        loading SPECTER2 on each call).

    Returns
    -------
    The updated DataFrame (already written to disk).
    """
    from cascade_rc.data.score_normalizer import compute_raw_scores

    scored_df = compute_raw_scores(parquet_path, query, _encoder=_encoder)
    # scored_df columns: pmid, bm25, specter2_cos, raw_score, y_abstract
    # pmid is str on both sides

    df = pd.read_parquet(parquet_path)

    score_map: dict[str, float] = dict(
        zip(scored_df["pmid"].astype(str), scored_df["raw_score"].astype(float))
    )
    df["s"] = df["pmid"].astype(str).map(score_map).fillna(0.0).astype("float64")
    df["u"] = df["s"]

    df.to_parquet(parquet_path, index=False)

    n_scored = int((df["s"] > 0.0).sum())
    logger.info(
        "%s updated: s/u added — %d/%d docs with non-zero score",
        parquet_path.name, n_scored, len(df),
    )
    return df


def main() -> None:
    from cascade_rc.data.clef_tar_loader import (
        _ALLOWED_TOPICS,
        _DEFAULT_CACHE_DIR,
        load_topic,
    )

    parser = argparse.ArgumentParser(
        description=(
            "Enrich CLEF-TAR topic parquets with hybrid-ranker s/u score columns."
        )
    )
    parser.add_argument(
        "--topics",
        nargs="+",
        choices=sorted(_ALLOWED_TOPICS),
        metavar="TOPIC_ID",
        help=f"Topic IDs to process. Choices: {sorted(_ALLOWED_TOPICS)}. "
             "Default: all six topics.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("artefacts/cascade_rc/data"),
        help="Directory containing the topic parquets (default: artefacts/cascade_rc/data).",
    )
    parser.add_argument(
        "--clef-dir",
        type=Path,
        default=None,
        help="Root directory of the CLEF-TAR data tree "
             "(default: ~/.cache/cascade_rc/tar).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    topics: list[str] = args.topics or sorted(_ALLOWED_TOPICS)
    clef_dir: Path = args.clef_dir or _DEFAULT_CACHE_DIR

    missing_parquets = [
        t for t in topics
        if not (args.data_dir / f"{t}.parquet").exists()
    ]
    if missing_parquets:
        logger.warning(
            "No parquet found for topics (skipping): %s\n"
            "Run python -m cascade_rc.data.clef_tar_loader first.",
            sorted(missing_parquets),
        )

    for topic_id in topics:
        parquet_path = args.data_dir / f"{topic_id}.parquet"
        if not parquet_path.exists():
            continue

        try:
            topic = load_topic(topic_id, clef_dir)
            query = f"{topic.title} {topic.boolean_query}"
        except Exception as exc:
            logger.warning(
                "Could not load topic metadata for %s (%s); using topic_id as query.",
                topic_id, exc,
            )
            query = topic_id

        logger.info("Scoring %s …", topic_id)
        df = add_scores_to_parquet(parquet_path, query)

        s_min, s_max, s_mean = df["s"].min(), df["s"].max(), df["s"].mean()
        print(
            f"{topic_id}  rows={len(df)}"
            f"  s_min={s_min:.6f}  s_max={s_max:.6f}  s_mean={s_mean:.6f}"
            f"  cols={df.columns.tolist()}"
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
