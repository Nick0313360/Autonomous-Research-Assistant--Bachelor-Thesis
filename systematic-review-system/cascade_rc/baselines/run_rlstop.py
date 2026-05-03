"""RLStop baseline driver for CASCADE-RC.

Trains one PPO model per target_recall (4 models) on CLEF 2017 vendor data,
then applies each model to CLEF-TAR 2019 test topics ranked by BM25.

THREAD SAFETY NOTE: TAREnv reads 8 module-level globals from rlstop_tar_env.
Global mutation is not thread-safe. n_jobs=1 is enforced throughout — the
24-inference run takes minutes serially and parallelism is unnecessary.

Usage:
    python -m cascade_rc.baselines.run_rlstop \\
        --data-dir  data/clef_tar \\
        --out-dir   artefacts/baselines/rlstop \\
        --train-dir artefacts/baselines/rlstop \\
        [--topics CD008874 ...] \\
        [--recalls 0.80 0.90 0.95 1.0] \\
        [--skip-train] \\
        [--force-retrain] \\
        [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import random
import resource
from pathlib import Path

import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi

from cascade_rc.evaluation.metrics import wss_at_recall

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
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

_VECTOR_SIZE = 100  # TAREnv observation dimension

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

_VENDOR = Path(__file__).parent / "rlstop_vendor"


# ---------------------------------------------------------------------------
# make_windows — referenced as a global inside TAREnv; not in the vendor code
# ---------------------------------------------------------------------------

def _make_windows(vector_size: int, n_docs: int) -> list[tuple[int, int]]:
    """Divide n_docs into vector_size equal windows of (start, end) index pairs."""
    window_size = max(1, n_docs // vector_size)
    return [(i * window_size, (i + 1) * window_size) for i in range(vector_size)]


# ---------------------------------------------------------------------------
# Training data helpers
# ---------------------------------------------------------------------------

def _load_training_qrels(vendor_dir: Path) -> dict[str, dict[str, int]]:
    """Parse CLEF2017_qrels.txt into {topic_id: {pmid: 0|1}}."""
    qrels_path = vendor_dir / "data" / "qrels" / "CLEF2017_qrels.txt"
    qrels: dict[str, dict[str, int]] = {}
    for line in qrels_path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        topic, pmid, rel = parts[0], parts[2], int(parts[3])
        qrels.setdefault(topic, {})[pmid] = rel
    return qrels


def _build_training_dicts(
    vendor_dir: Path,
) -> tuple[dict[str, list[str]], dict[str, list[int]]]:
    """Build doc_rank_dic and rank_rel_dic from CLEF 2017 vendor data.

    doc_rank_dic:  {topic_id: [pmid, ...]}  — PMIDs in pre-ranked order
    rank_rel_dic:  {topic_id: [0|1, ...]}   — relevance label in rank order
    """
    docids_dir = vendor_dir / "data" / "clef2017" / "docids"
    qrels = _load_training_qrels(vendor_dir)

    doc_rank_dic: dict[str, list[str]] = {}
    rank_rel_dic: dict[str, list[int]] = {}

    for docid_file in sorted(docids_dir.iterdir()):
        topic_id = docid_file.name
        pmids = [p.strip() for p in docid_file.read_text().splitlines() if p.strip()]
        if len(pmids) < _VECTOR_SIZE:
            logger.warning(
                "Skipping training topic %s: %d docs < vector_size=%d",
                topic_id, len(pmids), _VECTOR_SIZE,
            )
            continue
        doc_rank_dic[topic_id] = pmids
        topic_q = qrels.get(topic_id, {})
        rank_rel_dic[topic_id] = [topic_q.get(pmid, 0) for pmid in pmids]

    return doc_rank_dic, rank_rel_dic


# ---------------------------------------------------------------------------
# BM25 ranking for test topics
# ---------------------------------------------------------------------------

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


def _bm25_rank(df: pd.DataFrame, query: str) -> list[str]:
    """Return PMIDs sorted by BM25 score descending using query tokens."""
    corpus = [
        (str(r.title or "") + " " + str(r.abstract or "")).lower().split()
        for r in df.itertuples()
    ]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query.lower().split())
    ranked_idx = np.argsort(-scores)
    return df["pmid"].iloc[ranked_idx].tolist()


# ---------------------------------------------------------------------------
# Global injection into TAREnv
# ---------------------------------------------------------------------------

def _inject_globals(
    topic_id: str,
    doc_rank_dic: dict[str, list[str]],
    rank_rel_dic: dict[str, list[int]],
) -> None:
    """Inject all module-level globals required by TAREnv before instantiation."""
    import cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env as _env_mod
    import cascade_rc.baselines.rlstop_vendor.rl_utils.ranking_utils as _rank_mod

    _env_mod.doc_rank_dic = doc_rank_dic
    _env_mod.rank_rel_dic = rank_rel_dic
    _env_mod.SELECTED_TOPICS = []
    _env_mod.TRAINING = True
    _env_mod.SELECTED_TOPICS_ORDERERD = [topic_id]
    _env_mod.SELECTED_TOPICS_ORDERERD_INDEX = 0
    _env_mod.make_windows = _make_windows
    _env_mod.get_rel_cnt_rate = _rank_mod.get_rel_cnt_rate
    _env_mod.random = random

    _rank_mod.doc_rank_dic = doc_rank_dic
    _rank_mod.rank_rel_dic = rank_rel_dic
    _rank_mod.make_windows = _make_windows


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def _linear_schedule(initial_value: float):
    def func(progress_remaining: float) -> float:
        return progress_remaining * initial_value
    return func


def _train_model(
    target_recall: float,
    train_doc_rank_dic: dict[str, list[str]],
    train_rank_rel_dic: dict[str, list[int]],
    cache_path: Path,
    force_retrain: bool = False,
):
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import DummyVecEnv
    from cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env import TAREnv
    import cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env as _env_mod

    if cache_path.exists() and not force_retrain:
        logger.info("Loading cached model: %s", cache_path)
        return PPO.load(str(cache_path))

    train_topics = sorted(train_doc_rank_dic.keys())

    _env_mod.TRAINING = True
    _env_mod.SELECTED_TOPICS_ORDERERD = train_topics
    _env_mod.SELECTED_TOPICS_ORDERERD_INDEX = 0

    def _make_env(t_id: str):
        def _fn():
            _inject_globals(t_id, train_doc_rank_dic, train_rank_rel_dic)
            return TAREnv(target_recall=target_recall, topic_id=t_id, size=_VECTOR_SIZE)
        return _fn

    vec_env = DummyVecEnv([_make_env(t) for t in train_topics])

    model = PPO(
        policy="MlpPolicy",
        env=vec_env,
        n_steps=100,
        batch_size=100,
        n_epochs=8,
        gamma=0.99,
        gae_lambda=0.98,
        ent_coef=0.01,
        clip_range=0.2,
        learning_rate=_linear_schedule(1e-4),
        seed=0,
        verbose=0,
    )
    logger.info(
        "Training PPO for target_recall=%.2f (%d topics) ...",
        target_recall, len(train_topics),
    )
    model.learn(total_timesteps=100_000)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(cache_path))
    logger.info("Model saved: %s", cache_path)
    return model


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _infer_one(
    topic_id: str,
    df: pd.DataFrame,
    target_recall: float,
    model,
    data_dir: Path,
) -> dict:
    from cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env import TAREnv

    query = _get_topic_title(topic_id, data_dir)
    ranked_pmids = _bm25_rank(df, query)
    all_pmids = df["pmid"].tolist()
    y_true = df["y_abstract"].to_numpy(dtype=np.int64)

    pmid_to_y = dict(zip(df["pmid"].tolist(), df["y_abstract"].tolist()))
    infer_doc_rank = {topic_id: ranked_pmids}
    infer_rank_rel = {topic_id: [int(pmid_to_y.get(pmid, 0)) for pmid in ranked_pmids]}

    _inject_globals(topic_id, infer_doc_rank, infer_rank_rel)
    env = TAREnv(target_recall=target_recall, topic_id=topic_id, size=_VECTOR_SIZE)
    obs, _ = env.reset()

    for _ in range(_VECTOR_SIZE + 1):
        action, _ = model.predict(obs, deterministic=True)
        obs, _, terminated, truncated, _ = env.step(int(action))
        if terminated or truncated:
            break

    examined = int(env.n_samp_docs)
    examined_pmids = set(ranked_pmids[:examined])

    predictions = np.isin(all_pmids, list(examined_pmids)).astype(int)
    wss = wss_at_recall(predictions, y_true, target_recall=0.95)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "method":          "rlstop",
        "topic_id":        topic_id,
        "target_recall":   target_recall,
        "examined":        examined,
        "recall_achieved": wss["achieved_recall"],
        "wss_95":          wss["wss"],
        "wss_status":      wss["status"],
        "peak_rss_kb":     peak_rss,
    }


# ---------------------------------------------------------------------------
# Public sweep entry point
# ---------------------------------------------------------------------------

def _empty_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in _OUTPUT_SCHEMA.items()})


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    train_dir: Path,
    topics: list[str] = DEFAULT_TOPICS,
    recalls: list[float] = DEFAULT_RECALLS,
    skip_train: bool = False,
    force_retrain: bool = False,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run RLStop sweep and write rlstop_results.parquet to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    train_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df = _empty_df()
        df.to_parquet(out_dir / "rlstop_results.parquet", index=False)
        logger.info("DRY-RUN: 0-row schema parquet written to %s", out_dir)
        return df

    available = [t for t in topics if (data_dir / f"{t}.parquet").exists()]
    if not available:
        raise FileNotFoundError(f"No topic parquets found in {data_dir}")
    skipped = set(topics) - set(available)
    if skipped:
        logger.warning("Skipping topics (parquet not found): %s", sorted(skipped))

    train_doc_rank_dic, train_rank_rel_dic = _build_training_dicts(_VENDOR)

    readme_path = out_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# RLStop Model Weights\n\n"
            "Naming:     `recall_<target_recall>.zip`  (SB3 PPO format)\n"
            "Trained on: CLEF 2017 (42 Intervention topics, vendor-provided rankings)\n"
            "PPO steps:  100 000\n"
            "Hyperparams: n_steps=100 batch_size=100 n_epochs=8 gamma=0.99 gae_lambda=0.98\n"
            "             ent_coef=0.01 clip_range=0.2 lr=linear_schedule(1e-4) seed=0\n"
            "Applied to: all available CLEF-TAR 2019 test topics "
            "(cross-family — see VENDORED_FROM)\n"
        )

    rows: list[dict] = []
    for target_recall in recalls:
        cache_path = train_dir / f"recall_{target_recall:.2f}.zip"
        if not skip_train:
            model = _train_model(
                target_recall, train_doc_rank_dic, train_rank_rel_dic,
                cache_path, force_retrain=force_retrain,
            )
        else:
            from stable_baselines3 import PPO
            if not cache_path.exists():
                raise FileNotFoundError(
                    f"--skip-train requested but model not found: {cache_path}"
                )
            model = PPO.load(str(cache_path))

        for topic_id in available:
            df_topic = pd.read_parquet(data_dir / f"{topic_id}.parquet")
            logger.info("RLStop infer: %s @ recall=%.2f", topic_id, target_recall)
            row = _infer_one(topic_id, df_topic, target_recall, model, data_dir)
            rows.append(row)
            logger.info(
                "  examined=%d  wss_status=%s", row["examined"], row["wss_status"]
            )

    df = pd.DataFrame(rows).astype(_OUTPUT_SCHEMA)
    out_path = out_dir / "rlstop_results.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows to %s", len(df), out_path)
    return df


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run RLStop baseline sweep.")
    p.add_argument("--data-dir", type=Path, default=Path("data/clef_tar"))
    p.add_argument("--out-dir", type=Path, default=Path("artefacts/baselines/rlstop"))
    p.add_argument("--train-dir", type=Path, default=Path("artefacts/baselines/rlstop"),
                   help="Directory where model .zip files are cached.")
    p.add_argument("--topics", nargs="+", default=DEFAULT_TOPICS, metavar="TOPIC_ID")
    p.add_argument("--recalls", nargs="+", type=float, default=DEFAULT_RECALLS, metavar="RECALL")
    p.add_argument("--skip-train", action="store_true",
                   help="Load cached .zip models; fail if not present.")
    p.add_argument("--force-retrain", action="store_true",
                   help="Ignore cached .zip files and retrain from scratch.")
    p.add_argument("--dry-run", action="store_true",
                   help="Write 0-row schema parquet without training or inference.")
    return p


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _build_arg_parser().parse_args()
    run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        train_dir=args.train_dir,
        topics=args.topics,
        recalls=args.recalls,
        skip_train=args.skip_train,
        force_retrain=args.force_retrain,
        dry_run=args.dry_run,
    )
