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
