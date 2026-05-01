"""Tests for cascade_rc/calibration/surrogate_loss.py (Prompt 4.1).

Loss formula (Mondrian-on-Y=1, positives only):
    L̃(θ; s, u) = 1{s < λ_lo} | (1{λ_lo ≤ s < λ_hi} & 1{u ≥ τ_SE})
with θ = (λ_lo, λ_hi, τ_SE).
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from cascade_rc.calibration.surrogate_loss import grid, loss_tensor


# ---------------------------------------------------------------------------
# Reference (slow, single-point, full y support)
# ---------------------------------------------------------------------------

def loss_reference_python(
    theta: tuple[float, float, float],
    s: float,
    u: float,
    y: int,
) -> int:
    lam_lo, lam_hi, tau_se = theta
    term1 = s < lam_lo
    term2 = (lam_lo <= s < lam_hi) and (u >= tau_se)
    return int(y) * int(term1 or term2)


# ---------------------------------------------------------------------------
# test_loss_matches_reference
# ---------------------------------------------------------------------------

def test_loss_matches_reference() -> None:
    """Vectorised loss_tensor matches loss_reference_python on 10 000 positive points."""
    rng = np.random.default_rng(0)
    n = 10_000

    s_pos = rng.uniform(0.0, 1.0, n)
    u_pos = rng.uniform(0.0, 1.0, n)

    # Small hand-crafted theta grid
    theta_vals = np.array([
        [0.2, 0.7, 0.5],
        [0.0, 1.0, 0.0],
        [0.5, 0.5, 0.5],  # λ_lo == λ_hi edge case
        [0.9, 1.0, 0.3],
    ], dtype=np.float64)

    result = loss_tensor(theta_vals, s_pos, u_pos)  # (4, n)

    for g, theta in enumerate(theta_vals):
        for i in range(n):
            expected = loss_reference_python(
                (theta[0], theta[1], theta[2]), s_pos[i], u_pos[i], y=1
            )
            assert result[g, i] == expected, (
                f"Mismatch at g={g}, i={i}: got {result[g,i]}, expected {expected}"
            )


# ---------------------------------------------------------------------------
# test_loss_zero_when_y_zero
# ---------------------------------------------------------------------------

def test_loss_zero_when_y_zero() -> None:
    """loss_reference_python returns 0 for all theta when y=0."""
    rng = np.random.default_rng(1)
    theta_list = [
        (0.0, 1.0, 0.0),
        (0.2, 0.8, 0.4),
        (0.99, 1.0, 0.01),
    ]
    for _ in range(1000):
        s = float(rng.uniform())
        u = float(rng.uniform())
        for theta in theta_list:
            assert loss_reference_python(theta, s, u, y=0) == 0, (
                f"Expected 0 for y=0, theta={theta}, s={s:.3f}, u={u:.3f}"
            )


# ---------------------------------------------------------------------------
# test_loss_monotone_in_lambda_lo
# ---------------------------------------------------------------------------

def test_loss_monotone_in_lambda_lo() -> None:
    """For fixed (λ_hi, τ_SE), increasing λ_lo cannot decrease the loss (Lemma 6)."""
    rng = np.random.default_rng(2)
    n = 500

    s_pos = rng.uniform(0.0, 1.0, n)
    u_pos = rng.uniform(0.0, 1.0, n)

    lam_hi = 0.7
    tau_se = 0.4
    lo_values = np.linspace(0.0, lam_hi, 15)  # increasing λ_lo, all ≤ λ_hi

    theta_grid = np.column_stack([
        lo_values,
        np.full(len(lo_values), lam_hi),
        np.full(len(lo_values), tau_se),
    ])

    losses = loss_tensor(theta_grid, s_pos, u_pos)  # (15, n)
    mean_losses = losses.mean(axis=1)  # (15,)

    # mean loss must be non-decreasing as λ_lo increases
    diffs = np.diff(mean_losses)
    assert np.all(diffs >= -1e-12), (
        f"Loss decreased when λ_lo increased: diffs = {diffs}"
    )


# ---------------------------------------------------------------------------
# test_grid_constrained
# ---------------------------------------------------------------------------

def test_grid_constrained() -> None:
    """Every point in grid(K) satisfies λ_lo ≤ λ_hi."""
    for K in (5, 10, 20):
        g = grid(K)
        assert g.ndim == 2 and g.shape[1] == 3, f"K={K}: expected (G,3), got {g.shape}"
        lam_lo = g[:, 0]
        lam_hi = g[:, 1]
        violations = np.sum(lam_lo > lam_hi + 1e-12)
        assert violations == 0, (
            f"K={K}: {violations} grid points violate λ_lo ≤ λ_hi"
        )
        # values in [0,1]
        assert np.all(g >= 0.0) and np.all(g <= 1.0 + 1e-12), (
            f"K={K}: grid values outside [0,1]"
        )


# ---------------------------------------------------------------------------
# test_performance_acceptance
# ---------------------------------------------------------------------------

def test_performance_acceptance() -> None:
    """loss_tensor for K=20, n_pos=121 completes in < 50 ms (acceptance criterion)."""
    rng = np.random.default_rng(99)
    n_pos = 121
    s_pos = rng.uniform(0.0, 1.0, n_pos)
    u_pos = rng.uniform(0.0, 1.0, n_pos)

    theta_grid = grid(20)

    start = time.perf_counter()
    result = loss_tensor(theta_grid, s_pos, u_pos)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert elapsed_ms < 50, (
        f"loss_tensor took {elapsed_ms:.1f} ms, expected < 50 ms"
    )
    assert result.shape[1] == n_pos


# ---------------------------------------------------------------------------
# test_slack_tensor_values
# ---------------------------------------------------------------------------

def test_slack_tensor_values() -> None:
    """η_i = 1 only in uncertain zone with SE firing and LLM correct (y_hat==1).

    Grid point: λ_lo=0.3, λ_hi=0.7, τ_SE=0.5.
    Paper cases:
      idx 0: s=0.1 < λ_lo            → L̃=1, L=1, η=0
      idx 1: s=0.5, u=0.6≥τ_SE, ŷ=1 → L̃=1, L=0, η=1  (uncertain+SE+correct)
      idx 2: s=0.5, u=0.6≥τ_SE, ŷ=0 → L̃=1, L=1, η=0  (uncertain+SE+wrong)
      idx 3: s=0.5, u=0.4<τ_SE       → L̃=0, L=0, η=0  (uncertain, SE silent)
      idx 4: s=0.9 ≥ λ_hi            → L̃=0, L=0, η=0  (auto-include)
    """
    from cascade_rc.calibration.surrogate_loss import slack_tensor

    theta = np.array([[0.3, 0.7, 0.5]])  # (1, 3)
    s_pos = np.array([0.1, 0.5, 0.5, 0.5, 0.9])
    u_pos = np.array([0.6, 0.6, 0.6, 0.4, 0.6])
    y_hat = np.array([1,   1,   0,   1,   1])

    slack = slack_tensor(theta, s_pos, u_pos, y_hat)

    assert slack.shape == (1, 5)
    np.testing.assert_array_equal(slack[0], [0, 1, 0, 0, 0])


# ---------------------------------------------------------------------------
# test_slack_non_negative_bounded_by_dominating_loss
# ---------------------------------------------------------------------------

def test_slack_non_negative_bounded_by_dominating_loss() -> None:
    """0 ≤ η_i(θ) ≤ L̃_i(θ) for all (θ, i) — Lemma 1 of the paper."""
    from cascade_rc.calibration.surrogate_loss import grid, loss_tensor, slack_tensor

    rng = np.random.default_rng(42)
    theta_g = grid(10)
    n = 200
    s = rng.uniform(0.0, 1.0, n)
    u = rng.uniform(0.0, 1.0, n)
    y_hat = rng.integers(0, 2, n)

    L_tilde = loss_tensor(theta_g, s, u).astype(np.float64)
    eta = slack_tensor(theta_g, s, u, y_hat).astype(np.float64)

    assert (eta >= 0).all(), "slack must be non-negative"
    assert (eta <= L_tilde).all(), "slack cannot exceed dominating loss"
