"""Evaluation metrics for CASCADE-RC systematic review screening."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def wss_at_recall(
    predictions: np.ndarray,
    y_true: np.ndarray,
    target_recall: float = 0.95,
) -> dict:
    """Work Saved over Sampling at target recall (CLEF / Cohen 2006 formula).

    WSS@r = (TN + FN) / N - (1 - r), evaluated at the certified θ̂ routing.

    Returns:
        dict with keys:
            wss (float | nan): WSS value, or nan if recall target was missed.
            achieved_recall (float): recall of the given predictions.
            status (str): "ok" | "recall_target_missed" | "no_relevant_docs".
    """
    n_relevant = int(np.sum(y_true == 1))
    if n_relevant == 0:
        return {
            "wss": float("nan"),
            "achieved_recall": float("nan"),
            "status": "no_relevant_docs",
        }
    achieved = float(np.sum((predictions == 1) & (y_true == 1)) / n_relevant)
    if achieved < target_recall:
        return {
            "wss": float("nan"),
            "achieved_recall": achieved,
            "status": "recall_target_missed",
        }
    tn = int(np.sum((predictions == 0) & (y_true == 0)))
    fn = int(np.sum((predictions == 0) & (y_true == 1)))
    n = len(y_true)
    wss = (tn + fn) / n - (1.0 - target_recall)
    return {"wss": wss, "achieved_recall": achieved, "status": "ok"}


def abstention_rate(certified: dict[str, dict]) -> float:
    """Fraction of topics that abstained. Returns nan for empty input.

    Args:
        certified: mapping topic_id → {status: "certified"|"abstained", ...}.

    Returns:
        Float in [0, 1], or nan if certified is empty.
    """
    if not certified:
        return float("nan")
    n_abstained = sum(1 for v in certified.values() if v.get("status") == "abstained")
    return float(n_abstained / len(certified))


_VALID_DECISIONS: frozenset[str] = frozenset(
    {"auto_accept", "auto_reject", "llm_escalate", "human_review"}
)


def llm_query_volume(routing: pd.DataFrame) -> dict:
    """Aggregate routing decisions into a volume breakdown dict.

    Args:
        routing: DataFrame with columns {pmid: str, decision: str} where
                 decision ∈ {auto_accept, auto_reject, llm_escalate, human_review}.

    Returns:
        dict with keys auto_accept, auto_reject, llm_escalate, human_review,
        total (int), llm_fraction (float).

    Raises:
        ValueError: if any decision value is not in _VALID_DECISIONS.
    """
    unknown = set(routing["decision"].unique()) - _VALID_DECISIONS
    if unknown:
        raise ValueError(f"Unexpected decision values: {unknown!r}")
    counts = routing["decision"].value_counts().to_dict()
    total = int(len(routing))
    llm_escalate = counts.get("llm_escalate", 0)
    return {
        "auto_accept":  int(counts.get("auto_accept", 0)),
        "auto_reject":  int(counts.get("auto_reject", 0)),
        "llm_escalate": int(llm_escalate),
        "human_review": int(counts.get("human_review", 0)),
        "total": total,
        "llm_fraction": llm_escalate / total if total > 0 else 0.0,
    }


def bootstrap_eta_upper(
    slack_mat: np.ndarray,
    delta: float,
    B: int = 1000,
    seed: int = 0,
) -> np.ndarray:
    """Bootstrap (1−delta) upper confidence bound on mean slack per grid point.

    Args:
        slack_mat: (G, m_plus) float64 from CertificationResult.slack_mat.
        delta:     Confidence level — use config.ltt.delta_bootstrap.
        B:         Number of bootstrap resamples (default 1000).
        seed:      RNG seed for reproducibility.

    Returns:
        (G,) array: for each grid point, the (1−delta)-quantile of B bootstrap means.
    """
    G, m_plus = slack_mat.shape
    rng = np.random.default_rng(seed)
    boot_means = np.empty((G, B), dtype=np.float64)
    for b in range(B):
        idx = rng.integers(0, m_plus, size=(G, m_plus))         # (G, m_plus)
        boot_means[:, b] = slack_mat[np.arange(G)[:, None], idx].mean(axis=1)
    return np.quantile(boot_means, 1.0 - delta, axis=1)         # (G,)


def slack_ratio_diagnostic(
    eta_lcb: np.ndarray,
    eta_boot_upper: np.ndarray,
) -> np.ndarray:
    """Element-wise tightness ratio η̂⁻⋆ / η̂⁺_boot (paper §9.4).

    Values ≈ 1: WSR LCB is tight relative to bootstrap estimate.
    Values << 1: bound is conservative.
    Returns nan where eta_boot_upper == 0.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(eta_boot_upper > 0.0, eta_lcb / eta_boot_upper, np.nan)
