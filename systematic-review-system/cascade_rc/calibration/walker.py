"""Safest-to-riskiest fixed-sequence walker for LTT grid calibration.

Implements the optimal walk order from Lemma 6 and the fixed-sequence
rejection procedure from Theorem 1 (Angelopoulos et al. 2021, LTT).

Walk order: lex-ascending in (λ_lo, λ_hi, τ_SE) so the safest operating
point (smallest thresholds) is tested first and the riskiest last.

Rejection rule: reject H_θ as long as p_HB(θ) ≤ δ_LTT; stop at first
acceptance.  The fixed-sequence structure gives FWER ≤ δ_LTT without
Bonferroni inflation (each test uses the full budget δ_LTT).
"""
from __future__ import annotations

import numpy as np


def safest_to_riskiest_order(grid: np.ndarray) -> np.ndarray:
    """Return indices that lex-sort the grid by (λ_lo, λ_hi, τ_SE) ascending.

    The "safest" point (0, 0, 0) is visited first; the "riskiest" last.

    Args:
        grid: (G, 3) array with columns [λ_lo, λ_hi, τ_SE].

    Returns:
        (G,) index array giving the walk order.
    """
    # np.lexsort: last key = primary sort key
    return np.lexsort((grid[:, 2], grid[:, 1], grid[:, 0]))


def walk_reject(
    p_values: np.ndarray,
    order: np.ndarray,
    delta_LTT: float,
) -> np.ndarray:
    """Fixed-sequence walk: reject H_θ for each θ in order until first acceptance.

    Per LTT Theorem 1, the fixed-sequence procedure controls FWER at δ_LTT
    without Bonferroni correction — each individual test uses the full budget.

    Args:
        p_values:  (G,) p-values, one per grid point.
        order:     (G,) walk order — indices into p_values (e.g. from
                   safest_to_riskiest_order).
        delta_LTT: Per-test rejection threshold δ_LTT.

    Returns:
        (G,) boolean mask; True at positions whose null was rejected.
    """
    rejected = np.zeros(len(order), dtype=bool)
    for idx in order:
        if p_values[idx] <= delta_LTT:
            rejected[idx] = True
        else:
            break
    return rejected
