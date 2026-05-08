"""Tests for cascade_rc/evaluation/metrics.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from cascade_rc.evaluation.metrics import (
    _derive_routing,
    _predictions_from_routing,
    abstention_rate,
    aggregate_cross_topic,
    bootstrap_eta_upper,
    compute_fnr,
    compute_routing_fractions,
    compute_slack_ratio,
    compute_wss,
    evaluate_certificate,
    llm_query_volume,
    slack_ratio_diagnostic,
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


def test_wss_at_recall_no_relevant_docs() -> None:
    """y_true all-zero → status='no_relevant_docs', wss=nan, achieved_recall=nan."""
    y_true      = np.array([0, 0, 0, 0, 0])
    predictions = np.array([1, 0, 1, 0, 0])
    result = wss_at_recall(predictions, y_true, target_recall=0.95)
    assert result["status"] == "no_relevant_docs"
    assert np.isnan(result["wss"])
    assert np.isnan(result["achieved_recall"])


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


# ---------------------------------------------------------------------------
# bootstrap_eta_upper
# ---------------------------------------------------------------------------

def test_bootstrap_eta_upper_shape() -> None:
    """Returns (G,) array for (G, m_plus) input."""
    rng = np.random.default_rng(0)
    G, m_plus = 5, 80
    slack_mat = rng.uniform(0.0, 0.3, size=(G, m_plus))
    upper = bootstrap_eta_upper(slack_mat, delta=0.05, B=500, seed=1)
    assert upper.shape == (G,)


def test_bootstrap_eta_upper_covers_sample_mean() -> None:
    """Bootstrap (1-delta) upper bound >= sample mean for all G rows (should hold always)."""
    rng = np.random.default_rng(42)
    G, m_plus = 4, 200
    slack_mat = rng.uniform(0.0, 0.3, size=(G, m_plus))
    upper = bootstrap_eta_upper(slack_mat, delta=0.05, B=2000, seed=0)
    sample_means = slack_mat.mean(axis=1)
    assert np.all(upper >= sample_means - 1e-9)


def test_bootstrap_eta_upper_deterministic() -> None:
    """Same seed yields identical result across two calls."""
    rng = np.random.default_rng(7)
    slack_mat = rng.uniform(0.0, 0.5, size=(3, 50))
    u1 = bootstrap_eta_upper(slack_mat, delta=0.10, B=200, seed=99)
    u2 = bootstrap_eta_upper(slack_mat, delta=0.10, B=200, seed=99)
    np.testing.assert_array_equal(u1, u2)


# ---------------------------------------------------------------------------
# slack_ratio_diagnostic
# ---------------------------------------------------------------------------

def test_slack_ratio_diagnostic_values() -> None:
    eta_lcb  = np.array([0.5, 0.8, 0.0])
    eta_boot = np.array([1.0, 1.0, 0.5])
    ratio = slack_ratio_diagnostic(eta_lcb, eta_boot)
    np.testing.assert_allclose(ratio, [0.5, 0.8, 0.0])


def test_slack_ratio_diagnostic_zero_denominator_gives_nan() -> None:
    """eta_boot_upper == 0 → nan (not a division error)."""
    eta_lcb  = np.array([0.5, 0.3])
    eta_boot = np.array([0.0, 1.0])
    ratio = slack_ratio_diagnostic(eta_lcb, eta_boot)
    assert np.isnan(ratio[0])
    assert ratio[1] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# _derive_routing
# ---------------------------------------------------------------------------

def test_derive_routing_all_four_decisions() -> None:
    """Each routing zone produces the correct decision."""
    # theta_hat = (lam_lo=0.3, lam_hi=0.7, tau_se=0.5)
    theta_hat = np.array([0.3, 0.7, 0.5])
    df = pd.DataFrame({
        "pmid": ["a", "b", "c", "d"],
        "s":    [0.1, 0.9, 0.5, 0.5],   # auto_reject, auto_accept, uncertain, uncertain
        "u":    [0.5, 0.5, 0.8, 0.2],   # (irrelevant), (irrelevant), llm_escalate, human_review
    })
    result = _derive_routing(df, theta_hat)
    assert list(result["decision"]) == [
        "auto_reject", "auto_accept", "llm_escalate", "human_review"
    ]


def test_derive_routing_does_not_mutate_input() -> None:
    """_derive_routing returns a copy and does not add 'decision' to the input df."""
    theta_hat = np.array([0.3, 0.7, 0.5])
    df = pd.DataFrame({"pmid": ["a"], "s": [0.5], "u": [0.6]})
    _derive_routing(df, theta_hat)
    assert "decision" not in df.columns


# ---------------------------------------------------------------------------
# _predictions_from_routing
# ---------------------------------------------------------------------------

def test_predictions_from_routing_screened_vs_skipped() -> None:
    """auto_accept/llm_escalate/human_review → 1; auto_reject → 0."""
    routing = pd.DataFrame({
        "pmid": ["a", "b", "c", "d"],
        "decision": ["auto_accept", "auto_reject", "llm_escalate", "human_review"],
    })
    preds = _predictions_from_routing(routing)
    np.testing.assert_array_equal(preds, [1, 0, 1, 1])


# ---------------------------------------------------------------------------
# Helpers shared by new metric tests
# ---------------------------------------------------------------------------

def _make_test_df(
    s: list[float],
    u: list[float],
    y: list[int],
    is_split: int = 2,
) -> pd.DataFrame:
    """Build a minimal dataframe for the test split."""
    return pd.DataFrame({
        "s": s,
        "u": u,
        "y_abstract": y,
        "is_split": [is_split] * len(s),
    })


# ---------------------------------------------------------------------------
# TASK 4, test 3: routing fractions sum to 1
# ---------------------------------------------------------------------------

def test_routing_fractions_sum_to_one() -> None:
    """cheap_reject + auto_include + escalated must equal exactly 1.0."""
    df = _make_test_df(
        s=[0.1, 0.2, 0.5, 0.6, 0.9],
        u=[0.0, 0.0, 0.8, 0.2, 0.0],
        y=[0,   1,   0,   1,   1],
    )
    theta_hat = (0.3, 0.7, 0.5)
    fracs = compute_routing_fractions(df, theta_hat)
    total = fracs["frac_cheap_reject"] + fracs["frac_auto_include"] + fracs["frac_escalated"]
    assert total == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# TASK 4, test 1: FNR is 0 when all records are auto-included
# ---------------------------------------------------------------------------

def test_fnr_zero_when_all_included() -> None:
    """λ_lo=0, λ_hi=0 → s >= λ_hi for all → auto-include → FNR must be 0."""
    df = _make_test_df(
        s=[0.0, 0.3, 0.7, 1.0],
        u=[0.5, 0.5, 0.5, 0.5],
        y=[1,   1,   0,   1],
    )
    theta_hat = (0.0, 0.0, 0.5)
    fnr = compute_fnr(df, theta_hat)
    assert fnr == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# TASK 4, test 2: WSS is NaN when recall target is not achieved
# ---------------------------------------------------------------------------

def test_wss_nan_when_recall_missed() -> None:
    """High λ_lo rejects everything → recall=0 < 0.95 → compute_wss returns NaN."""
    df = _make_test_df(
        s=[0.1, 0.2, 0.3],
        u=[0.5, 0.5, 0.5],
        y=[1,   1,   0],
    )
    theta_hat = (0.99, 1.0, 0.5)  # λ_lo=0.99 → all cheap-rejected, recall=0
    wss = compute_wss(df, theta_hat, recall_target=0.95)
    assert math.isnan(wss)


# ---------------------------------------------------------------------------
# Additional compute_routing_fractions tests
# ---------------------------------------------------------------------------

def test_routing_fractions_all_cheap_reject() -> None:
    """All s < λ_lo → frac_cheap_reject=1, all others=0."""
    df = _make_test_df(s=[0.1, 0.2], u=[0.5, 0.5], y=[1, 0])
    fracs = compute_routing_fractions(df, theta_hat=(0.5, 0.8, 0.5))
    assert fracs["frac_cheap_reject"] == pytest.approx(1.0)
    assert fracs["frac_auto_include"] == pytest.approx(0.0)
    assert fracs["frac_escalated"] == pytest.approx(0.0)
    assert fracs["llm_abstention_rate"] == pytest.approx(0.0)


def test_routing_fractions_llm_abstention_rate() -> None:
    """llm_abstention_rate = frac_human_review / frac_escalated."""
    # 4 records: 2 llm_followed (u>=0.5), 2 human_review (u<0.5)
    df = _make_test_df(
        s=[0.5, 0.5, 0.5, 0.5],
        u=[0.8, 0.9, 0.2, 0.1],
        y=[0, 0, 1, 1],
    )
    fracs = compute_routing_fractions(df, theta_hat=(0.3, 0.8, 0.5))
    assert fracs["frac_escalated"] == pytest.approx(1.0)
    assert fracs["llm_abstention_rate"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Additional compute_fnr tests
# ---------------------------------------------------------------------------

def test_fnr_no_positives_returns_zero() -> None:
    """No positive labels → FNR defaults to 0.0."""
    df = _make_test_df(s=[0.1, 0.9], u=[0.5, 0.5], y=[0, 0])
    assert compute_fnr(df, theta_hat=(0.3, 0.7, 0.5)) == pytest.approx(0.0)


def test_fnr_all_positives_cheap_rejected() -> None:
    """All positives below λ_lo → FNR = 1.0."""
    df = _make_test_df(s=[0.1, 0.2], u=[0.5, 0.5], y=[1, 1])
    fnr = compute_fnr(df, theta_hat=(0.5, 0.8, 0.5))
    assert fnr == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Additional compute_wss tests
# ---------------------------------------------------------------------------

def test_wss_all_auto_included_perfect_recall() -> None:
    """λ_lo=0, λ_hi=0 → all included → recall=1.0 → WSS = (FN+TN)/N - 0.05."""
    df = _make_test_df(
        s=[0.5, 0.5, 0.5, 0.5, 0.5],
        u=[0.5, 0.5, 0.5, 0.5, 0.5],
        y=[1,   1,   0,   0,   0],
    )
    wss = compute_wss(df, theta_hat=(0.0, 0.0, 0.5), recall_target=0.95)
    # All included, so TN=0, FN=0 — WSS = (0+0)/5 - 0.05 = -0.05
    assert not math.isnan(wss)
    assert wss == pytest.approx(-0.05, abs=1e-9)


# ---------------------------------------------------------------------------
# compute_slack_ratio
# ---------------------------------------------------------------------------

def test_compute_slack_ratio_normal() -> None:
    assert compute_slack_ratio(0.8, 1.0) == pytest.approx(0.8)


def test_compute_slack_ratio_zero_denominator_returns_nan() -> None:
    assert math.isnan(compute_slack_ratio(0.5, 0.0))


def test_compute_slack_ratio_tight_bound() -> None:
    """Values near 1.0 indicate tight bound."""
    assert compute_slack_ratio(0.99, 1.0) == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# evaluate_certificate
# ---------------------------------------------------------------------------

def _make_full_df() -> pd.DataFrame:
    """20-record df with is_split in {1,2} for evaluate_certificate."""
    rng = np.random.default_rng(0)
    n = 20
    return pd.DataFrame({
        "s": rng.uniform(0, 1, n),
        "u": rng.uniform(0, 1, n),
        "y_abstract": ([1] * 5 + [0] * 5) * 2,
        "is_split": ([1] * 10 + [2] * 10),
    })


def test_evaluate_certificate_returns_required_keys() -> None:
    """evaluate_certificate must return all Table-3 keys."""
    df = _make_full_df()
    result = evaluate_certificate(df, theta_hat=(0.0, 0.0, 0.5), alpha=0.10, B=5)
    required = {
        "fnr_test", "wss_95", "recall_achieved", "alpha",
        "certificate_valid", "n_test", "n_test_positives",
        "llm_calls_per_abstract", "frac_cheap_reject", "frac_auto_include",
        "frac_llm_followed", "frac_human_review", "frac_escalated",
        "llm_abstention_rate",
    }
    assert required <= set(result.keys())


def test_evaluate_certificate_valid_when_fnr_le_alpha() -> None:
    """certificate_valid is True iff fnr_test <= alpha."""
    df = _make_full_df()
    result = evaluate_certificate(df, theta_hat=(0.0, 0.0, 0.5), alpha=0.10, B=5)
    # With λ_lo=0,λ_hi=0 all auto-included → FNR=0 ≤ 0.10
    assert result["certificate_valid"] is True
    assert result["fnr_test"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# aggregate_cross_topic
# ---------------------------------------------------------------------------

def test_aggregate_cross_topic_mean_se() -> None:
    """Mean and SE are computed correctly over a simple list of dicts."""
    records = [
        {"fnr_test": 0.0, "wss_95": 0.4, "frac_human_review": 0.1, "llm_abstention_rate": 0.2},
        {"fnr_test": 0.1, "wss_95": 0.5, "frac_human_review": 0.2, "llm_abstention_rate": 0.3},
    ]
    out = aggregate_cross_topic(records)
    assert out["fnr_test_mean"] == pytest.approx(0.05)
    assert out["wss_95_mean"] == pytest.approx(0.45)
    assert out["fnr_test_n"] == 2


def test_aggregate_cross_topic_excludes_sentinel() -> None:
    """wss_95=-999.0 (NaN sentinel) must be excluded from aggregation."""
    records = [
        {"fnr_test": 0.0, "wss_95": -999.0, "frac_human_review": 0.1, "llm_abstention_rate": 0.1},
        {"fnr_test": 0.1, "wss_95": 0.5,    "frac_human_review": 0.2, "llm_abstention_rate": 0.2},
    ]
    out = aggregate_cross_topic(records)
    assert out["wss_95_n"] == 1
    assert out["wss_95_mean"] == pytest.approx(0.5)


def test_aggregate_cross_topic_empty_list() -> None:
    """Empty input → empty output dict (no KeyError)."""
    out = aggregate_cross_topic([])
    assert out == {}
