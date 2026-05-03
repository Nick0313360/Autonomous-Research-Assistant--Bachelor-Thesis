"""Tests for WSR betting-based LCB (cascade_rc/calibration/wsr_lcb.py).

TDD RED phase — written before implementation exists.
"""
from __future__ import annotations

import numpy as np
import pytest

from cascade_rc.calibration.wsr_lcb import wsr_lcb_grid, wsr_lcb_one_sided


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hoeffding_lcb(samples: np.ndarray, delta: float) -> float:
    """One-sided Hoeffding lower bound for [0,1]-bounded mean."""
    n = len(samples)
    return float(samples.mean() - np.sqrt(np.log(1.0 / delta) / (2.0 * n)))


# ---------------------------------------------------------------------------
# test_wsr_coverage_synthetic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delta", [0.05, 0.10])
def test_wsr_coverage_synthetic(delta: float) -> None:
    """LCB covers the true mean at least (1-delta) fraction of the time.

    1 000 independent trials, each with n=50 samples from Uniform(0, 0.3).
    True mean = 0.15.
    """
    rng = np.random.default_rng(0)
    n_trials = 1_000
    n_samples = 50
    true_mean = 0.15  # E[Uniform(0, 0.3)]

    covered = 0
    for _ in range(n_trials):
        samples = rng.uniform(0.0, 0.3, n_samples)
        lcb = wsr_lcb_one_sided(samples, delta=delta)
        if lcb <= true_mean:
            covered += 1

    empirical_coverage = covered / n_trials
    assert empirical_coverage >= 1.0 - delta, (
        f"Empirical coverage {empirical_coverage:.3f} < 1-delta={1-delta:.2f} "
        f"(delta={delta})"
    )


# ---------------------------------------------------------------------------
# test_wsr_tighter_than_hoeffding
# ---------------------------------------------------------------------------

def test_wsr_tighter_than_hoeffding() -> None:
    """WSR LCB should be tighter (higher) than the Hoeffding LCB on average.

    1 000 trials of n=50 samples from Uniform(0, 0.3) with delta=0.05.
    """
    rng = np.random.default_rng(1)
    n_trials = 1_000
    n_samples = 50
    delta = 0.05

    wsr_lcbs: list[float] = []
    hoeff_lcbs: list[float] = []

    for _ in range(n_trials):
        samples = rng.uniform(0.0, 0.3, n_samples)
        wsr_lcbs.append(wsr_lcb_one_sided(samples, delta=delta))
        hoeff_lcbs.append(_hoeffding_lcb(samples, delta=delta))

    mean_wsr = np.mean(wsr_lcbs)
    mean_hoeff = np.mean(hoeff_lcbs)
    assert mean_wsr > mean_hoeff, (
        f"WSR mean LCB {mean_wsr:.4f} not > Hoeffding mean LCB {mean_hoeff:.4f}"
    )


# ---------------------------------------------------------------------------
# test_wsr_zero_for_constant_zero_input
# ---------------------------------------------------------------------------

def test_wsr_zero_for_constant_zero_input() -> None:
    """All-zero samples → LCB = 0 (no betting power above zero)."""
    samples = np.zeros(50)
    lcb = wsr_lcb_one_sided(samples, delta=0.05)
    assert lcb == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# test_bonferroni_per_grid_point
# ---------------------------------------------------------------------------

def test_bonferroni_per_grid_point() -> None:
    """wsr_lcb_grid applies Bonferroni: each point gets delta_eta / num_grid_points.

    We pass three identical sample arrays and verify that the result matches
    wsr_lcb_one_sided called with delta = delta_eta / 3 for each point.
    """
    rng = np.random.default_rng(2)
    n_samples = 80
    base = rng.uniform(0.0, 0.3, n_samples)

    delta_eta = 0.12
    num_grid_points = 3
    slack_samples = np.stack([base, base, base])  # (3, n_samples)

    grid_lcbs = wsr_lcb_grid(slack_samples, delta_eta=delta_eta, num_grid_points=num_grid_points)

    per_point_delta = delta_eta / num_grid_points
    expected_lcb = wsr_lcb_one_sided(base, delta=per_point_delta)

    assert grid_lcbs.shape == (num_grid_points,)
    np.testing.assert_allclose(grid_lcbs, expected_lcb, rtol=1e-6)
