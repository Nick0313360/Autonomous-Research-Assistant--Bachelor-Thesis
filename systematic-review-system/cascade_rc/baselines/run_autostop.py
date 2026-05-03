"""AUTOSTOP baseline driver for CASCADE-RC.

Runs the AUTOSTOP CAL loop (Li & Kanoulas 2020) on each topic parquet and
produces autostop_results.parquet with the shared 8-column schema.

RET_DIR patching: autostop.tar_framework.utils.RET_DIR is a module-level
constant. The driver replaces it with a TemporaryDirectory for each run and
restores the original in a finally block to avoid cross-run pollution.

Usage:
    python -m cascade_rc.baselines.run_autostop \\
        --data-dir data/clef_tar \\
        --out-dir  artefacts/baselines/autostop \\
        [--topics CD008874 CD012080 CD012768] \\
        [--recalls 0.80 0.90 0.95 1.0] \\
        [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import resource
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from cascade_rc.evaluation.metrics import wss_at_recall

_VENDOR = Path(__file__).parent / "autostop_vendor"
sys.path.insert(0, str(_VENDOR))

import autostop.tar_framework.utils as _as_utils  # noqa: E402
from autostop.tar_model.auto_stop import autostop_method as _autostop_method  # noqa: E402

_ORIGINAL_RET_DIR: str = _as_utils.RET_DIR

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",   # DTA
    "CD011768", "CD011975", "CD011145",   # Intervention
]
DEFAULT_RECALLS: list[float] = [0.80, 0.90, 0.95, 1.0]

_TOPIC_FAMILY: dict[str, str] = {
    "CD008874": "DTA",
    "CD012080": "DTA",
    "CD012768": "DTA",
    "CD011768": "Intervention",
    "CD011975": "Intervention",
    "CD011145": "Intervention",
}

_OUTPUT_SCHEMA: dict[str, str] = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "int64",
}


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in _OUTPUT_SCHEMA.items()})


def _get_topic_title(topic_id: str, data_dir: Path) -> str:
    """Return the systematic review title from CLEF-TAR topic file, or topic_id as fallback."""
    family = _TOPIC_FAMILY.get(topic_id, "DTA")
    topic_path = data_dir / "2019-TAR" / "Task2" / "Testing" / family / "topics" / topic_id
    if not topic_path.exists():
        return topic_id
    try:
        from cascade_rc.data.clef_tar_loader import _parse_topic_file
        title, _, _ = _parse_topic_file(topic_path)
        return title or topic_id
    except Exception:
        return topic_id


def _run_one(
    topic_id: str,
    df: pd.DataFrame,
    target_recall: float,
    data_dir: Path,
) -> dict:
    """Run AUTOSTOP for a single (topic_id, target_recall) pair."""
    title = _get_topic_title(topic_id, data_dir)
    all_pmids: list[str] = df["pmid"].tolist()
    y_true = df["y_abstract"].to_numpy(dtype=np.int64)

    with tempfile.TemporaryDirectory() as _tmpdir:
        tmpdir = Path(_tmpdir)

        # Build temp input files
        (tmpdir / "query.json").write_text(json.dumps({"title": title}))

        with (tmpdir / "qrels.txt").open("w") as f:
            for _, row in df.iterrows():
                f.write(f"{topic_id} 0 {row['pmid']} {int(row['y_abstract'])}\n")

        (tmpdir / "docids.txt").write_text("\n".join(all_pmids))

        with (tmpdir / "docs.jsonl").open("w") as f:
            for _, row in df.iterrows():
                rec = {
                    "id": row["pmid"],
                    "title": row["title"] or "",
                    "content": row["abstract"] or "",
                }
                f.write(json.dumps(rec) + "\n")

        _as_utils.RET_DIR = str(tmpdir)
        try:
            _autostop_method(
                data_name="crc",
                topic_set="test",
                topic_id=topic_id,
                query_file=str(tmpdir / "query.json"),
                qrel_file=str(tmpdir / "qrels.txt"),
                doc_id_file=str(tmpdir / "docids.txt"),
                doc_text_file=str(tmpdir / "docs.jsonl"),
                sampler_type="HTAPPriorSampler",
                stopping_recall=target_recall,
                target_recall=1.0,
                stopping_condition="loose",
                random_state=0,
            )
        finally:
            _as_utils.RET_DIR = _ORIGINAL_RET_DIR

        # Parse interaction CSV: columns are
        # t, batch_size, total_num, sampled_num, total_true_r, total_esti_r,
        # var1, var2, running_true_r, ap, running_esti_recall, running_true_recall
        csv_paths = list(tmpdir.rglob(f"{topic_id}.csv"))
        if not csv_paths:
            raise FileNotFoundError(f"No interaction CSV found for {topic_id} in {tmpdir}")
        interaction = pd.read_csv(csv_paths[0], header=None)
        examined = int(interaction.iloc[-1][3])  # sampled_num at stopping

        # Parse TREC run file: topic_id\tAF|NF\tpmid\trank\tscore\tmrun
        run_paths = list(tmpdir.rglob(f"{topic_id}.run"))
        if not run_paths:
            raise FileNotFoundError(f"No run file found for {topic_id} in {tmpdir}")
        examined_pmids = {
            line.split()[2]
            for line in run_paths[0].read_text().splitlines()
            if line.strip()
        }

    predictions = np.isin(all_pmids, list(examined_pmids)).astype(int)
    wss = wss_at_recall(predictions, y_true, target_recall=0.95)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    wss_val = wss["wss"]
    return {
        "method":          "autostop",
        "topic_id":        topic_id,
        "target_recall":   target_recall,
        "examined":        examined,
        "recall_achieved": wss["achieved_recall"],
        "wss_95":          float("nan") if isinstance(wss_val, float) and np.isnan(wss_val) else wss_val,
        "wss_status":      wss["status"],
        "peak_rss_kb":     peak_rss,
    }


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics: list[str] = DEFAULT_TOPICS,
    recalls: list[float] = DEFAULT_RECALLS,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run AUTOSTOP sweep and write autostop_results.parquet to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df = _empty_df()
        df.to_parquet(out_dir / "autostop_results.parquet", index=False)
        logger.info("DRY-RUN: 0-row schema parquet written to %s", out_dir)
        return df

    available = [t for t in topics if (data_dir / f"{t}.parquet").exists()]
    if not available:
        raise FileNotFoundError(f"No topic parquets found in {data_dir}")
    skipped = set(topics) - set(available)
    if skipped:
        logger.warning("Skipping topics (parquet not found): %s", sorted(skipped))

    rows: list[dict] = []
    for topic_id in available:
        df_topic = pd.read_parquet(data_dir / f"{topic_id}.parquet")
        for target_recall in recalls:
            logger.info("AUTOSTOP: %s @ recall=%.2f", topic_id, target_recall)
            row = _run_one(topic_id, df_topic, target_recall, data_dir)
            rows.append(row)
            logger.info(
                "  examined=%d  wss_status=%s",
                row["examined"], row["wss_status"],
            )

    df = pd.DataFrame(rows).astype(_OUTPUT_SCHEMA)
    out_path = out_dir / "autostop_results.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows to %s", len(df), out_path)
    return df


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run AUTOSTOP baseline sweep.")
    p.add_argument("--data-dir", type=Path, default=Path("data/clef_tar"),
                   help="Directory containing <topic_id>.parquet files and 2019-TAR/ tree.")
    p.add_argument("--out-dir", type=Path, default=Path("artefacts/baselines/autostop"),
                   help="Output directory for autostop_results.parquet.")
    p.add_argument("--topics", nargs="+", default=DEFAULT_TOPICS, metavar="TOPIC_ID")
    p.add_argument("--recalls", nargs="+", type=float, default=DEFAULT_RECALLS, metavar="RECALL")
    p.add_argument("--dry-run", action="store_true",
                   help="Write 0-row schema parquet without calling autostop_method.")
    return p


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _build_arg_parser().parse_args()
    run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        topics=args.topics,
        recalls=args.recalls,
        dry_run=args.dry_run,
    )
