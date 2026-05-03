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
    """safest_to_riskiest_order produces strictly ascending lex order."""
    rng = np.random.default_rng(0)
    grid = rng.uniform(0.0, 1.0, size=(20, 3))
    order = safest_to_riskiest_order(grid)

    sorted_rows = grid[order]
    for i in range(len(sorted_rows) - 1):
        a, b = tuple(sorted_rows[i]), tuple(sorted_rows[i + 1])
        assert a <= b, f"Order not ascending at position {i}: {a} > {b}"
