"""Tests for safest-to-riskiest walker (cascade_rc/calibration/walker.py).

TDD RED phase — written before implementation exists.
"""
from __future__ import annotations

import numpy as np

from cascade_rc.calibration.walker import safest_to_riskiest_order, walk_reject


# ---------------------------------------------------------------------------
# test_walk_halts_at_first_acceptance
# ---------------------------------------------------------------------------

def test_walk_halts_at_first_acceptance() -> None:
    """Fixed-sequence walk rejects until the first acceptance, then stops.

    p-values [0.001, 0.001, 0.5, 0.001] with identity order and delta=0.05:
    indices 0 and 1 are rejected; index 2 exceeds delta so the walk halts;
    index 3 is never visited, so it stays False.
    """
    p_values = np.array([0.001, 0.001, 0.5, 0.001])
    order = np.array([0, 1, 2, 3])
    delta_LTT = 0.05

    rejected = walk_reject(p_values, order, delta_LTT)

    assert rejected[0], "index 0 (p=0.001) should be rejected"
    assert rejected[1], "index 1 (p=0.001) should be rejected"
    assert not rejected[2], "index 2 (p=0.5) caused acceptance — should not be rejected"
    assert not rejected[3], "index 3 was never visited — should not be rejected"


# ---------------------------------------------------------------------------
# test_safest_first
# ---------------------------------------------------------------------------

def test_safest_first() -> None:
    """safest_to_riskiest_order visits the all-zero point first.

    Grid: [(0.5,0.5,0.5), (0.0,0.0,0.0), (0.9,0.9,0.9)].
    Lexicographically smallest by (λ_lo, λ_hi, τ_SE) is (0,0,0) at index 1.
    """
    grid = np.array([[0.5, 0.5, 0.5],
                     [0.0, 0.0, 0.0],
                     [0.9, 0.9, 0.9]])

    order = safest_to_riskiest_order(grid)

    assert order[0] == 1, (
        f"Expected first walk index 1 ((0,0,0)), got {order[0]}"
    )
    assert order[2] == 2, (
        f"Expected last walk index 2 ((0.9,0.9,0.9)), got {order[2]}"
    )


# ---------------------------------------------------------------------------
# test_walk_all_rejected
# ---------------------------------------------------------------------------

def test_walk_all_rejected() -> None:
    """Walk rejects all hypotheses when every p-value ≤ delta."""
    p_values = np.array([0.01, 0.02, 0.03])
    order = np.array([0, 1, 2])
    rejected = walk_reject(p_values, order, delta_LTT=0.05)
    assert rejected.all(), "All p-values below delta — all should be rejected"


# ---------------------------------------------------------------------------
# test_walk_none_rejected
# ---------------------------------------------------------------------------

def test_walk_none_rejected() -> None:
    """Walk rejects nothing when the very first p-value exceeds delta."""
    p_values = np.array([0.5, 0.01, 0.01])
    order = np.array([0, 1, 2])
    rejected = walk_reject(p_values, order, delta_LTT=0.05)
    assert not rejected.any(), "First p-value above delta — nothing should be rejected"


# ---------------------------------------------------------------------------
# test_lexsort_order_ascending
# ---------------------------------------------------------------------------

def test_lexsort_order_ascending() -> None:
    """safest_to_riskiest_order produces lex order: λ_lo ASC, λ_hi ASC, τ_SE DESC."""
    rng = np.random.default_rng(0)
    grid = rng.uniform(0.0, 1.0, size=(20, 3))
    order = safest_to_riskiest_order(grid)

    sorted_rows = grid[order]
    # Adjust τ_SE to negative so the full triple is non-decreasing
    adjusted = sorted_rows.copy()
    adjusted[:, 2] = -adjusted[:, 2]
    for i in range(len(adjusted) - 1):
        a, b = tuple(adjusted[i]), tuple(adjusted[i + 1])
        assert a <= b, f"Order not (λ_lo ASC, λ_hi ASC, τ_SE DESC) at position {i}: {a} > {b}"


# ---------------------------------------------------------------------------
# test_tau_SE_traversal_direction
# ---------------------------------------------------------------------------

def test_tau_SE_traversal_direction() -> None:
    """τ_SE must be traversed DESC (large to small) in the S→R walk."""
    # Build a tiny 2x2x2 grid: λ_lo ∈ {0,1}, λ_hi ∈ {0,1}, τ_SE ∈ {0,1}
    grid = np.array([
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
        [0.0, 1.0, 1.0],
        [1.0, 0.0, 0.0],
        [1.0, 0.0, 1.0],
        [1.0, 1.0, 0.0],
        [1.0, 1.0, 1.0],
    ])
    order = safest_to_riskiest_order(grid)
    # The FIRST point visited must have τ_SE = 1.0 (safest τ_SE corner)
    first_point = grid[order[0]]
    assert first_point[2] == 1.0, (
        f"Walk must START at τ_SE=1.0 (safest), got τ_SE={first_point[2]}. "
        f"This is the τ_SE traversal direction bug."
    )
    # The LAST point visited must have τ_SE = 0.0 (riskiest τ_SE corner)
    last_point = grid[order[-1]]
    assert last_point[2] == 0.0, (
        f"Walk must END at τ_SE=0.0 (riskiest), got τ_SE={last_point[2]}."
    )
    # Safest overall corner: (0, 0, 1) — λ_lo=0, λ_hi=0, τ_SE=1
    assert list(first_point) == [0.0, 0.0, 1.0], (
        f"Safest corner must be (λ_lo=0, λ_hi=0, τ_SE=1), got {list(first_point)}"
    )


# ---------------------------------------------------------------------------
# test_loss_zero_at_safest_corner
# ---------------------------------------------------------------------------

def test_loss_zero_at_safest_corner() -> None:
    """At (λ_lo=min, λ_hi=min, τ_SE=1.0), L̃ should be near 0 for positives."""
    from cascade_rc.calibration.surrogate_loss import loss_tensor, grid

    K = 5
    g = grid(K)
    # Safest corner: λ_lo=0, λ_hi=0, τ_SE=1.0
    # With λ_hi≈0, every positive is auto-included → L̃=0
    s_pos = np.array([0.3, 0.5, 0.7, 0.9])
    u_pos = np.array([0.5, 0.5, 0.5, 0.5])

    L = loss_tensor(g, s_pos, u_pos)
    # Find the row closest to (0,0,1)
    safest_idx = int(np.argmin(g[:, 0] + g[:, 1] + (1 - g[:, 2])))
    assert L[safest_idx].mean() < 0.1, (
        f"Safest corner should have near-zero loss, got {L[safest_idx].mean():.3f}"
    )
