"""Selective Conformal Risk Control (SCRC-I and SCRC-T) baseline.

Reference: Xu, Guo, Wei, "Selective Conformal Risk Control", arXiv:2512.12844
Supporting: Angelopoulos et al., "Conformal Risk Control", arXiv:2208.02814
"""
from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from cascade_rc.evaluation.metrics import wss_at_recall

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]
DEFAULT_RECALLS: list[float] = [0.80, 0.90, 0.95, 1.0]
DEFAULT_VARIANTS: list[str] = ["I", "T"]

_OUTPUT_SCHEMA: dict[str, str] = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "float64",  # always np.nan — see spec §5
}


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------

def _crc_threshold(pos_scores: np.ndarray, alpha: float) -> float:
    """Split-conformal FNR quantile threshold.

    Among n_pos calibration positive scores and one exchangeable test positive,
    ranks are uniform on {0,...,n_pos} (0-indexed). P(s_test < pos_scores[k])
    equals (k+1)/(n_pos+1) — NOT k/(n_pos+1). To achieve FNR ≤ alpha we need
    (k+1)/(n_pos+1) ≤ alpha, i.e. k ≤ alpha*(n_pos+1) - 1, so:

        k = floor(alpha * (n_pos + 1)) - 1
        lambda_star = pos_scores[k]

    Edge cases:
    - n_pos == 0: return 0.0 (no information → accept everything)
    - k < 0:     return 0.0 (alpha too small for n_pos → accept everything, FNR=0)
    - k >= n_pos: return 0.0 (only possible when alpha ≈ 1, defensive)

    Args:
        pos_scores: (n_pos,) array of positive scores, sorted ascending.
        alpha:      Risk level in [0, 1].

    Returns:
        Scalar threshold lambda_star >= 0.
    """
    n_pos = len(pos_scores)
    if n_pos == 0:
        return 0.0
    k = int(math.floor(alpha * (n_pos + 1))) - 1
    if k < 0:
        return 0.0
    if k >= n_pos:
        return 0.0
    return float(pos_scores[k])


# ---------------------------------------------------------------------------
# SCRC class
# ---------------------------------------------------------------------------

class SCRC:
    """Selective Conformal Risk Control for TAR document screening.

    Two variants:
      "I" (inductive)    — splits calibration 50/50; fits tau on C1, lambda_star on C2.
      "T" (transductive) — uses full calibration for both; LOO via n_pos+1 correction.

    Usage::

        scrc = SCRC(variant="I", alpha=0.10)
        scrc.fit(s_cal, u_cal, y_cal)
        decisions = scrc.predict(s_test, u_test)   # "accept" | "abstain"

    Fitted attributes (available after fit()):
        tau_         — selection threshold on u; abstain if u < tau_
        lambda_star_ — CRC acceptance threshold on s; accept if s >= lambda_star_
        n_pos_used_  — calibration positives used for lambda_star_ (diagnostic)
    """

    def __init__(
        self,
        variant: Literal["I", "T"],
        alpha: float,
        abstain_rate: float = 0.1,
        split_ratio: float = 0.5,
        seed: int = 0,
    ) -> None:
        if variant not in ("I", "T"):
            raise ValueError(f"variant must be 'I' or 'T', got {variant!r}")
        if not (0.0 <= alpha <= 1.0):
            raise ValueError(f"alpha must be in [0, 1], got {alpha}")
        if not (0.0 <= abstain_rate < 1.0):
            raise ValueError(f"abstain_rate must be in [0, 1), got {abstain_rate}")
        self.variant = variant
        self.alpha = alpha
        self.abstain_rate = abstain_rate
        self.split_ratio = split_ratio
        self.seed = seed
        self._fitted = False

    # ------------------------------------------------------------------
    # fit
    # ------------------------------------------------------------------

    def fit(
        self,
        s: np.ndarray,
        u: np.ndarray,
        y: np.ndarray,
    ) -> "SCRC":
        """Fit selection threshold tau_ and CRC threshold lambda_star_.

        Args:
            s: (n,) relevance scores in [0, 1].
            u: (n,) utility/confidence scores in [0, 1].
            y: (n,) binary labels {0, 1}.

        Returns:
            self
        """
        s = np.asarray(s, dtype=np.float64)
        u = np.asarray(u, dtype=np.float64)
        y = np.asarray(y, dtype=np.int64)

        if self.variant == "I":
            self._fit_inductive(s, u, y)
        else:
            self._fit_transductive(s, u, y)

        self._fitted = True
        return self

    def _fit_inductive(
        self, s: np.ndarray, u: np.ndarray, y: np.ndarray
    ) -> None:
        rng = np.random.default_rng(self.seed)

        pos_idx = np.where(y == 1)[0]
        neg_idx = np.where(y == 0)[0]
        rng.shuffle(pos_idx)
        rng.shuffle(neg_idx)

        n_pos_c1 = int(math.floor(len(pos_idx) * self.split_ratio))
        n_neg_c1 = int(math.floor(len(neg_idx) * self.split_ratio))

        c1_idx = np.concatenate([pos_idx[:n_pos_c1], neg_idx[:n_neg_c1]])
        c2_idx = np.concatenate([pos_idx[n_pos_c1:], neg_idx[n_neg_c1:]])

        u_c1 = u[c1_idx]
        s_c2, u_c2, y_c2 = s[c2_idx], u[c2_idx], y[c2_idx]

        self.tau_: float = float(np.quantile(u_c1, self.abstain_rate))
        selected_c2 = u_c2 >= self.tau_
        pos_mask = selected_c2 & (y_c2 == 1)
        pos_scores = np.sort(s_c2[pos_mask])
        self.lambda_star_: float = _crc_threshold(pos_scores, self.alpha)
        self.n_pos_used_: int = int(pos_mask.sum())

    def _fit_transductive(
        self, s: np.ndarray, u: np.ndarray, y: np.ndarray
    ) -> None:
        self.tau_: float = float(np.quantile(u, self.abstain_rate))
        selected = u >= self.tau_
        pos_mask = selected & (y == 1)
        pos_scores = np.sort(s[pos_mask])
        self.lambda_star_: float = _crc_threshold(pos_scores, self.alpha)
        self.n_pos_used_: int = int(pos_mask.sum())

    # ------------------------------------------------------------------
    # predict
    # ------------------------------------------------------------------

    def predict(self, s: np.ndarray, u: np.ndarray) -> np.ndarray:
        """Classify each document as 'accept' or 'abstain'.

        Returns an object-dtype array with values in {"accept", "abstain"}.
        Accepts a document iff u >= tau_ AND s >= lambda_star_.

        Raises:
            RuntimeError: if called before fit().
        """
        if not self._fitted:
            raise RuntimeError(
                "SCRC.predict() called before fit(). Call fit(s, u, y) first."
            )
        s = np.asarray(s, dtype=np.float64)
        u = np.asarray(u, dtype=np.float64)
        accepted = (u >= self.tau_) & (s >= self.lambda_star_)
        return np.where(accepted, "accept", "abstain").astype(object)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(
        {col: pd.Series(dtype=dt) for col, dt in _OUTPUT_SCHEMA.items()}
    )


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics: list[str] = DEFAULT_TOPICS,
    recalls: list[float] = DEFAULT_RECALLS,
    variants: list[str] = DEFAULT_VARIANTS,
    abstain_rate: float = 0.1,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run SCRC sweep and write scrc_results.parquet to out_dir.

    Args:
        data_dir:     Directory containing per-topic parquets with columns
                      pmid, s, u, y_abstract, is_calib.
        out_dir:      Output directory; scrc_results.parquet written here.
        topics:       List of topic IDs to process.
        recalls:      List of target recall levels (alpha = 1 - recall).
        variants:     List of SCRC variants to run ("I", "T").
        abstain_rate: Quantile of u used for abstention threshold tau.
        dry_run:      If True, write 0-row schema parquet without fitting.

    Returns:
        DataFrame with 8 columns per _OUTPUT_SCHEMA (48 rows if all defaults).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df = _empty_df()
        df.to_parquet(out_dir / "scrc_results.parquet", index=False)
        logger.info("DRY-RUN: 0-row schema parquet written to %s", out_dir)
        return df

    available = [t for t in topics if (data_dir / f"{t}.parquet").exists()]
    if not available:
        raise FileNotFoundError(f"No topic parquets found in {data_dir}")
    skipped = set(topics) - set(available)
    if skipped:
        logger.warning("Skipping topics (parquet not found): %s", sorted(skipped))

    rows: list[dict] = []
    for variant in variants:
        method = f"scrc_{variant.lower()}"
        for target_recall in recalls:
            alpha = 1.0 - target_recall
            for topic_id in available:
                df_topic = pd.read_parquet(data_dir / f"{topic_id}.parquet")
                cal = df_topic[df_topic["is_calib"] == 1]
                test = df_topic[df_topic["is_calib"] == 0]

                scrc = SCRC(variant=variant, alpha=alpha, abstain_rate=abstain_rate)
                scrc.fit(
                    cal["s"].to_numpy(dtype=np.float64),
                    cal["u"].to_numpy(dtype=np.float64),
                    cal["y_abstract"].to_numpy(dtype=np.int64),
                )
                decisions = scrc.predict(
                    test["s"].to_numpy(dtype=np.float64),
                    test["u"].to_numpy(dtype=np.float64),
                )

                examined = int((decisions == "accept").sum())
                predictions = (decisions == "accept").astype(np.int64)
                y_true = test["y_abstract"].to_numpy(dtype=np.int64)
                wss = wss_at_recall(predictions, y_true, target_recall=target_recall)

                row: dict = {
                    "method":          method,
                    "topic_id":        topic_id,
                    "target_recall":   float(target_recall),
                    "examined":        examined,
                    "recall_achieved": float(wss["achieved_recall"])
                                       if wss["achieved_recall"] == wss["achieved_recall"]
                                       else float("nan"),
                    "wss_95":          float(wss["wss"])
                                       if wss["wss"] == wss["wss"]
                                       else float("nan"),
                    "wss_status":      wss["status"],
                    # peak_rss_kb is always NaN: SCRC has constant per-cell memory cost.
                    # Column retained for pd.concat schema parity with AUTOSTOP/RLStop.
                    "peak_rss_kb":     float("nan"),
                }
                rows.append(row)
                logger.info(
                    "SCRC-%s %s @ recall=%.2f  examined=%d  wss_status=%s",
                    variant, topic_id, target_recall, examined, wss["status"],
                )

    df = pd.DataFrame(rows).astype(_OUTPUT_SCHEMA)
    out_path = out_dir / "scrc_results.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows to %s", len(df), out_path)
    return df


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run SCRC-I and SCRC-T baseline sweep.")
    p.add_argument("--data-dir",     type=Path, default=Path("artefacts/cascade_rc/data"))
    p.add_argument("--out-dir",      type=Path, default=Path("artefacts/baselines/scrc"))
    p.add_argument("--topics",       nargs="+", default=DEFAULT_TOPICS, metavar="TOPIC_ID")
    p.add_argument("--recalls",      nargs="+", type=float, default=DEFAULT_RECALLS, metavar="RECALL")
    p.add_argument("--variants",     nargs="+", default=DEFAULT_VARIANTS, choices=["I", "T"])
    p.add_argument("--abstain-rate", type=float, default=0.1,
                   help="Quantile of u for abstention threshold (default 0.1)")
    p.add_argument("--dry-run",      action="store_true",
                   help="Write 0-row schema parquet without fitting models.")
    return p


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _build_arg_parser().parse_args()
    run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        topics=args.topics,
        recalls=args.recalls,
        variants=args.variants,
        abstain_rate=args.abstain_rate,
        dry_run=args.dry_run,
    )
