"""Tests for cascade_rc/evaluation/metrics.py."""
from __future__ import annotations

import numpy as np
import pytest

from cascade_rc.evaluation.metrics import wss_at_recall


# ---------------------------------------------------------------------------
# wss_at_recall
# ---------------------------------------------------------------------------

def test_wss_at_recall_hand_computed() -> None:
    """10-doc corpus, 3 positives, 5 screened (all positives in screened set).

    TP=3, FP=2, TN=5, FN=0, N=10, recall=1.0.
    WSS@0.95 = (TN+FN)/N - (1-r) = (5+0)/10 - (1-0.95) = 0.50 - 0.05 = 0.45
    """
    y_true      = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    predictions = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
    result = wss_at_recall(predictions, y_true, target_recall=0.95)
    assert result["status"] == "ok"
    assert result["achieved_recall"] == pytest.approx(1.0)
    assert result["wss"] == pytest.approx(0.45, abs=1e-9)


def test_wss_at_recall_monotone_in_target() -> None:
    """For fixed predictions with achieved_recall=1.0, wss increases with target_recall."""
    y_true      = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
    predictions = np.array([1, 1, 1, 1, 1, 1, 0, 0, 0, 0])  # recall=5/5=1.0
    wss_70 = wss_at_recall(predictions, y_true, target_recall=0.70)["wss"]
    wss_95 = wss_at_recall(predictions, y_true, target_recall=0.95)["wss"]
    assert wss_70 < wss_95


def test_wss_at_recall_recall_target_missed() -> None:
    """achieved_recall < target → status='recall_target_missed', wss=nan."""
    y_true      = np.array([1, 1, 1, 0, 0])
    predictions = np.array([1, 0, 0, 0, 0])  # recall=1/3 ≈ 0.33
    result = wss_at_recall(predictions, y_true, target_recall=0.95)
    assert result["status"] == "recall_target_missed"
    assert np.isnan(result["wss"])
    assert result["achieved_recall"] == pytest.approx(1.0 / 3.0, rel=1e-6)
