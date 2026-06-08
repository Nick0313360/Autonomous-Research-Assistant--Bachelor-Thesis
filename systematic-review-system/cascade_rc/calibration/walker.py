"""Safest-to-riskiest fixed-sequence walker for LTT grid calibration.

Implements the optimal walk order from Lemma 6 and the fixed-sequence
rejection procedure from Theorem 1 (Angelopoulos et al. 2021, LTT).

Walk order: λ_lo ASC, λ_hi ASC, τ_SE DESC — so the safest operating
point (λ_lo=min, λ_hi=min, τ_SE=max) is tested first and the riskiest last.

Rejection rule: reject H_θ as long as p_HB(θ) ≤ δ_LTT; stop at first
acceptance.  The fixed-sequence structure gives FWER ≤ δ_LTT without
Bonferroni inflation (each test uses the full budget δ_LTT).
"""
from __future__ import annotations

import numpy as np


def safest_to_riskiest_order(grid: np.ndarray) -> np.ndarray:
    """
    Safest-to-Riskiest ordering for the three-route cascade.

    Monotonicity of L̃(θ; ω) = y·[1{s<λ_lo} + 1{λ_lo≤s<λ_hi}·1{u≥τ_SE}]:
      λ_lo: increasing → more cheap-rejects → more FN → risk increases → ASC
      λ_hi: increasing → fewer auto-includes → more LLM queries → risk increases → ASC
      τ_SE: increasing → stricter gate → more human routing → risk DECREASES → DESC

    Safest corner: (λ_lo=min, λ_hi=min, τ_SE=max)
    Riskiest corner: (λ_lo=max, λ_hi=max, τ_SE=min)

    np.lexsort: last key = primary sort key; sorts ASC by default.
    Negate τ_SE column to achieve DESC sort on τ_SE.
    """
    tau_SE_desc = -grid[:, 2]   # negate for descending sort
    return np.lexsort((tau_SE_desc, grid[:, 1], grid[:, 0]))


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


def holm_bonferroni_reject(
    p_values: np.ndarray,
    delta_LTT: float,
) -> np.ndarray:
    """Holm-Bonferroni step-down procedure over the full calibration grid.

    Unlike the fixed-sequence walk, every grid point is evaluated before
    any rejection decision is made, making the certified set robust to
    localised variance bumps in the risk landscape.

    Procedure:
      1. Sort p-values ascending: p_(1) ≤ p_(2) ≤ … ≤ p_(M).
      2. Reject H_θ_(i) if p_(i) ≤ δ_LTT / (M − i)  [0-indexed].
      3. Stop at the first i that fails; all prior indices are certified.

    FWER control: each step uses a Bonferroni threshold that accounts only
    for the hypotheses not yet rejected, giving strictly more power than a
    flat Bonferroni correction while maintaining FWER ≤ δ_LTT.

    Args:
        p_values:  (G,) p-values, one per grid point.
        delta_LTT: FWER budget δ_LTT.

    Returns:
        (G,) boolean mask; True at certified (rejected) positions.
    """
    M = len(p_values)
    sorted_idx = np.argsort(p_values)   # ascending order: p_(0) ≤ … ≤ p_(M-1)
    rejected = np.zeros(M, dtype=bool)
    for i, idx in enumerate(sorted_idx):
        if p_values[idx] <= delta_LTT / (M - i):   # Holm threshold at step i
            rejected[idx] = True
        else:
            break
    return rejected
