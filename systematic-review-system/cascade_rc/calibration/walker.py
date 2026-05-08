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
