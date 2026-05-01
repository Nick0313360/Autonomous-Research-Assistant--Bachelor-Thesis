"""Tests for cascade_rc/evaluation/metrics.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cascade_rc.evaluation.metrics import (
    abstention_rate,
    llm_query_volume,
    wss_at_recall,
)


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


# ---------------------------------------------------------------------------
# abstention_rate
# ---------------------------------------------------------------------------

def test_abstention_rate_all_certified() -> None:
    certified = {
        "CD008874": {"status": "certified"},
        "CD012080": {"status": "certified"},
    }
    assert abstention_rate(certified) == pytest.approx(0.0)


def test_abstention_rate_mixed() -> None:
    certified = {
        "CD008874": {"status": "certified"},
        "CD012080": {"status": "abstained"},
        "CD011768": {"status": "abstained"},
        "CD011975": {"status": "certified"},
    }
    assert abstention_rate(certified) == pytest.approx(0.5)


def test_abstention_rate_empty_returns_nan() -> None:
    assert np.isnan(abstention_rate({}))


# ---------------------------------------------------------------------------
# llm_query_volume
# ---------------------------------------------------------------------------

def test_llm_query_volume_counts() -> None:
    routing = pd.DataFrame({
        "pmid": ["1", "2", "3", "4", "5", "6"],
        "decision": [
            "auto_accept", "auto_reject", "auto_reject",
            "llm_escalate", "human_review", "human_review",
        ],
    })
    result = llm_query_volume(routing)
    assert result["auto_accept"] == 1
    assert result["auto_reject"] == 2
    assert result["llm_escalate"] == 1
    assert result["human_review"] == 2
    assert result["total"] == 6
    assert result["llm_fraction"] == pytest.approx(1.0 / 6.0)


def test_llm_query_volume_unknown_decision_raises() -> None:
    routing = pd.DataFrame({"pmid": ["1"], "decision": ["tier_4_special"]})
    with pytest.raises(ValueError, match="Unexpected decision values"):
        llm_query_volume(routing)
