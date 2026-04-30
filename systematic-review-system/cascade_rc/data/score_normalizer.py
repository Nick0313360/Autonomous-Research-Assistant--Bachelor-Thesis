"""
cascade_rc/data/score_normalizer.py
=====================================
Platt-scaled score normaliser for the Tier-2 hybrid ranker.

Workflow
--------
1. compute_raw_scores() — run the Tier-2 hybrid BM25+SPECTER2 ranker and
   return per-document scores (bm25, specter2_cos, raw_score).
2. fit_platt()          — fit a Platt calibration (logistic regression) on a
   stratified hold-out split.
3. apply_platt()        — project raw scores → calibrated P(Y=1|x) ∈ [0, 1].

CLI
---
python -m cascade_rc.data.score_normalizer --topic CD008874
"""
from __future__ import annotations

import logging
import joblib
import pickle
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression

from tier2_screening.hybrid_retriever import HybridRetriever
from infrastructure.encoder import SharedEncoderService
from models.data_classes import CandidateRecord

logger = logging.getLogger(__name__)

# Type alias: a Platt calibrator is a fitted single-feature LogisticRegression
PlattCalibrator = LogisticRegression

_RRF_K = 60

# ---------------------------------------------------------------------------
# CalibratorBundle — unified predict() wrapper around the persisted dict
# ---------------------------------------------------------------------------


class CalibratorBundle:
    """Runtime wrapper around a joblib-persisted calibrator dict."""

    def __init__(self, bundle: dict[str, Any]) -> None:
        self._chosen: str = bundle["chosen"]
        self._iso: IsotonicRegression = bundle["isotonic"]
        self._platt: LogisticRegression = bundle["platt"]
        self.metadata: dict[str, Any] = bundle.get("metadata", {})

    def predict(self, s: np.ndarray) -> np.ndarray:
        """Return calibrated probabilities for raw RRF scores *s*.

        Always returns shape (n,) float64, values clipped to [0, 1].
        Returns np.array([], dtype=float64) for empty input without raising.
        """
        s = np.atleast_1d(np.asarray(s, dtype=np.float64))
        if s.size == 0:
            return np.array([], dtype=np.float64)
        if self._chosen == "isotonic":
            out = self._iso.predict(s)
        elif self._chosen == "platt":
            out = self._platt.predict_proba(s.reshape(-1, 1))[:, 1]
        else:
            raise ValueError(
                f"Unknown calibrator type {self._chosen!r}; expected 'isotonic' or 'platt'."
            )
        return np.clip(out, 0.0, 1.0).astype(np.float64)

    @property
    def chosen(self) -> str:
        return self._chosen

    @property
    def nll(self) -> float:
        return float(self.metadata.get(f"nll_{self._chosen}", float("nan")))


def save_calibrator(bundle_dict: dict, path: Path) -> None:
    """Persist a calibrator bundle dict to *path* using joblib."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle_dict, path)
    logger.info("Saved calibrator bundle → %s", path)


def load_calibrator(path: Path) -> CalibratorBundle:
    """Load a joblib-persisted bundle and return a CalibratorBundle."""
    return CalibratorBundle(joblib.load(path))


def fit_calibrators(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
) -> dict[str, Any]:
    """Fit iso + Platt on train fold; pick lower-NLL on val fold; return bundle dict."""
    import datetime
    from sklearn.metrics import brier_score_loss, log_loss

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(x_train, y_train)

    platt = LogisticRegression(
        C=1e10, solver="lbfgs", max_iter=1000, random_state=42
    )
    platt.fit(x_train.reshape(-1, 1), y_train)

    # Clip isotonic predictions away from 0/1 to avoid infinite log-loss
    p_iso = np.clip(iso.predict(x_val), 1e-15, 1.0 - 1e-15)
    p_platt = np.clip(platt.predict_proba(x_val.reshape(-1, 1))[:, 1], 1e-15, 1.0 - 1e-15)

    nll_iso = float(log_loss(y_val, p_iso))
    nll_platt = float(log_loss(y_val, p_platt))
    brier_iso = float(brier_score_loss(y_val, p_iso))
    brier_platt = float(brier_score_loss(y_val, p_platt))

    chosen = "isotonic" if nll_iso <= nll_platt else "platt"
    logger.info(
        "fit_calibrators: chosen=%s  NLL iso=%.4f platt=%.4f  "
        "Brier iso=%.4f platt=%.4f",
        chosen, nll_iso, nll_platt, brier_iso, brier_platt,
    )

    return {
        "chosen": chosen,
        "isotonic": iso,
        "platt": platt,
        "metadata": {
            "nll_isotonic": nll_iso,
            "nll_platt": nll_platt,
            "brier_isotonic": brier_iso,
            "brier_platt": brier_platt,
            "n_train": int(len(x_train)),
            "n_val": int(len(x_val)),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_raw_scores(
    topic_parquet: Path,
    query: str,
    _encoder: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Run the Tier-2 hybrid ranker on *topic_parquet* and return raw scores.

    Parameters
    ----------
    topic_parquet : Path
        Parquet with columns pmid, title, abstract, y_abstract.
    query : str
        Review query string (topic title + boolean query concatenated).
    _encoder :
        Injected SharedEncoderService (used in tests to avoid loading SPECTER2).
        If None, a new SharedEncoderService() is created.

    Returns
    -------
    pd.DataFrame with columns: pmid, bm25, specter2_cos, raw_score, y_abstract
    """
    df = pd.read_parquet(topic_parquet)

    candidates: list[CandidateRecord] = [
        CandidateRecord(
            source_database="clef_tar",
            title=str(row["title"]),
            abstract=str(row["abstract"]),
            pmid=str(row["pmid"]),
            record_id=str(row["pmid"]),
        )
        for _, row in df.iterrows()
    ]

    encoder = _encoder if _encoder is not None else SharedEncoderService()
    retriever = HybridRetriever()
    retriever.build_indices(candidates, encoder)

    q_vec = encoder.embed_batch([query], head_name="abstract")[0]
    ranked = retriever.rank(candidates, q_vec, pico_query_text=query)

    records: list[dict[str, Any]] = [
        {
            "pmid": rc.candidate.pmid,
            "bm25": 1.0 / (_RRF_K + rc.bm25_rank),
            "specter2_cos": 1.0 / (_RRF_K + rc.dense_rank),
            "raw_score": rc.rrf_score,
        }
        for rc in ranked
    ]

    scores_df = pd.DataFrame(records)
    y_df = df[["pmid", "y_abstract"]].copy()
    y_df["pmid"] = y_df["pmid"].astype(str)

    return scores_df.merge(y_df, on="pmid", how="inner")


def fit_platt(raw_scores: np.ndarray, y: np.ndarray) -> PlattCalibrator:
    """
    Fit a Platt calibration on (raw_scores, y).

    Uses sklearn LogisticRegression (single feature: raw_score).

    Parameters
    ----------
    raw_scores : np.ndarray, shape (n,)
    y :          np.ndarray of int {0, 1}, shape (n,)

    Returns
    -------
    Fitted LogisticRegression (PlattCalibrator).
    """
    X = raw_scores.reshape(-1, 1)
    clf = LogisticRegression(solver="lbfgs", max_iter=1000, random_state=42)
    clf.fit(X, y)
    return clf


def apply_platt(calibrator: PlattCalibrator, raw_scores: np.ndarray) -> np.ndarray:
    """
    Apply a fitted Platt calibrator to project raw scores into [0, 1].

    Parameters
    ----------
    calibrator :  Fitted PlattCalibrator (LogisticRegression).
    raw_scores :  np.ndarray, shape (n,)

    Returns
    -------
    np.ndarray of float32, shape (n,), values in [0, 1].
    """
    X = raw_scores.reshape(-1, 1)
    return calibrator.predict_proba(X)[:, 1].astype(np.float32)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _reliability_plot(
    s_scores: np.ndarray,
    y: np.ndarray,
    n_bins: int,
    out_path: Path,
    topic_id: str,
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_mean_pred: list[float] = []
    bin_frac_pos: list[float] = []

    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (s_scores >= lo) & (s_scores < hi)
        if mask.sum() == 0:
            continue
        bin_mean_pred.append(float(s_scores[mask].mean()))
        bin_frac_pos.append(float(y[mask].mean()))

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k--", label="Perfect calibration")
    ax.scatter(bin_mean_pred, bin_frac_pos, label=f"{n_bins}-bin reliability")
    ax.set_xlabel("Mean predicted P(Y=1)")
    ax.set_ylabel("Fraction of positives")
    ax.set_title(f"Reliability plot — {topic_id}")
    ax.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved reliability plot → %s", out_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import sys

    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedShuffleSplit

    # Ensure repo root is on sys.path when invoked as a script
    _repo_root = Path(__file__).parent.parent.parent.resolve()
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

    from cascade_rc.data.clef_tar_loader import load_topic

    parser = argparse.ArgumentParser(
        description="Fit Platt calibration on CLEF-TAR topic Tier-2 scores."
    )
    parser.add_argument(
        "--topic",
        required=True,
        choices=["CD008874", "CD012080", "CD012768"],
        help="CLEF-TAR 2019 DTA topic ID.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Root data directory (default: <repo>/data).",
    )
    args = parser.parse_args()

    topic_id: str = args.topic
    data_dir: Path = args.data_dir or (_repo_root / "data")
    clef_dir: Path = data_dir / "clef_tar"

    parquet_path = clef_dir / f"{topic_id}.parquet"
    if not parquet_path.exists():
        sys.exit(
            f"ERROR: {parquet_path} not found.\n"
            "Run: python -m cascade_rc.data.clef_tar_loader "
            f"--topic {topic_id} --out {clef_dir}"
        )

    # Build query from topic metadata; fall back gracefully if not available
    try:
        topic = load_topic(topic_id, data_dir)
        query = f"{topic.title} {topic.boolean_query}"
    except Exception as exc:
        logger.warning(
            "Could not load topic metadata (%s); using topic_id as query.", exc
        )
        query = topic_id

    logger.info("Computing raw scores for %s …", topic_id)
    scored_df = compute_raw_scores(parquet_path, query)

    # Attach title + abstract from the original parquet (needed for output)
    original_df = pd.read_parquet(parquet_path)
    original_df["pmid"] = original_df["pmid"].astype(str)
    scored_df = scored_df.merge(
        original_df[["pmid", "title", "abstract"]].drop_duplicates("pmid"),
        on="pmid",
        how="left",
    )

    raw_scores = scored_df["raw_score"].to_numpy()
    y = scored_df["y_abstract"].to_numpy().astype(int)

    # Stratified 80/20 split (20% Platt-fit set, 80% evaluation set)
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(sss.split(raw_scores, y))

    x_train, y_train = raw_scores[train_idx], y[train_idx]
    x_test, y_test = raw_scores[test_idx], y[test_idx]

    logger.info("Fitting Platt calibrator on %d samples …", len(x_train))
    calibrator = fit_platt(x_train, y_train)
    s_test = apply_platt(calibrator, x_test)

    # ---- Metrics -----------------------------------------------------------
    auc_raw = roc_auc_score(y_test, x_test)
    auc_s = roc_auc_score(y_test, s_test)
    print(f"AUC (raw_score) : {auc_raw:.4f}")
    print(f"AUC (s_score)   : {auc_s:.4f}")

    # ---- Reliability plot --------------------------------------------------
    reports_dir = _repo_root / "reports"
    _reliability_plot(
        s_test,
        y_test,
        n_bins=10,
        out_path=reports_dir / f"{topic_id}_reliability.png",
        topic_id=topic_id,
    )

    # ---- Save outputs ------------------------------------------------------
    test_df = scored_df.iloc[test_idx].copy()
    test_df["s_score"] = s_test.astype(np.float32)
    out_cols = ["pmid", "title", "abstract", "raw_score", "s_score", "y_abstract"]

    clef_dir.mkdir(parents=True, exist_ok=True)
    scored_parquet = clef_dir / f"{topic_id}_scored.parquet"
    test_df[out_cols].to_parquet(scored_parquet, index=False)
    logger.info("Saved scored parquet → %s", scored_parquet)

    platt_pkl = clef_dir / f"{topic_id}_platt.pkl"
    with open(platt_pkl, "wb") as fh:
        pickle.dump(calibrator, fh)
    logger.info("Saved Platt calibrator → %s", platt_pkl)

    print(f"Scored parquet   → {scored_parquet}")
    print(f"Platt calibrator → {platt_pkl}")
    print(f"Reliability plot → {reports_dir / f'{topic_id}_reliability.png'}")


if __name__ == "__main__":
    main()
