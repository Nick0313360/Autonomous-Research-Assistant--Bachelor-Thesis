"""Hoeffding-Bentkus hybrid p-value for LTT grid calibration.

Implements the HB p-value from LTT Proposition 1:
  Angelopoulos et al. (2021) "Learn then Test", arXiv:2110.01052
  Bates et al. (2021) RCPS, arXiv:2101.02703

For null H_θ : R(θ) > α†, given empirical risk R̂_θ and n calibration samples:

  p_HB(θ) = min(
      exp(-n · h₁(min(R̂_θ, α†), α†)),        # Hoeffding KL bound
      e · P[Bin(n, α†) ≤ ⌈n · R̂_θ⌉]          # Bentkus binomial bound
  )

where h₁(a, b) = a·log(a/b) + (1-a)·log((1-a)/(1-b)) for a ≤ b, else 1.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import binom


def _h1_scalar(a: float, b: float) -> float:
    """KL divergence h₁(a, b) for scalars; returns 1 when a > b."""
    if a > b:
        return 1.0
    if a == b:
        return 0.0
    term1 = a * np.log(a / b) if a > 0.0 else 0.0
    term2 = (1.0 - a) * np.log((1.0 - a) / (1.0 - b)) if b < 1.0 else 0.0
    return float(term1 + term2)


def _h1_vec(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Vectorised h₁; a must satisfy a ≤ b element-wise (enforced by caller)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        term1 = np.where(a > 0.0, a * np.log(a / b), 0.0)
        term2 = np.where(b < 1.0, (1.0 - a) * np.log((1.0 - a) / (1.0 - b)), 0.0)
    return term1 + term2


def hb_pvalue_scalar(R_hat: float, alpha_dagger: float, n: int) -> float:
    """Single-θ HB p-value — reference implementation for cross-checking.

    Equivalent to MAPIE's _hoeffding_bentkus_p_value for the one-sided case.

    Args:
        R_hat:         Empirical risk R̂_θ ∈ [0, 1].
        alpha_dagger:  Corrected target α† = α + η̂⁻⋆(θ).
        n:             Number of Mondrian-positive calibration samples m₊.

    Returns:
        Scalar p-value in [0, 1].
    """
    a = min(R_hat, alpha_dagger)
    hoeff = float(np.exp(-n * _h1_scalar(a, alpha_dagger)))
    k = int(np.ceil(n * R_hat))
    bentkus = np.e * float(binom.cdf(k, n, alpha_dagger))
    return min(hoeff, bentkus)


def hb_pvalues(
    R_hat: np.ndarray,
    alpha_dagger: np.ndarray,
    n: int,
) -> np.ndarray:
    """Vectorised HB p-values over a grid of G configurations θ.

    Args:
        R_hat:         (G,) empirical risks R̂_θ ∈ [0, 1].
        alpha_dagger:  (G,) corrected targets α† = α + η̂⁻⋆(θ).
        n:             Number of Mondrian-positive calibration samples m₊.

    Returns:
        (G,) p-values in [0, 1].
    """
    R_hat = np.asarray(R_hat, dtype=np.float64)
    alpha_dagger = np.asarray(alpha_dagger, dtype=np.float64)

    # Hoeffding KL piece — R̂ clipped from above so h₁ is defined (a ≤ b)
    a = np.minimum(R_hat, alpha_dagger)
    hoeff = np.exp(-n * _h1_vec(a, alpha_dagger))

    # Bentkus binomial piece: e · P[Bin(n, α†) ≤ ⌈n · R̂⌉]
    k = np.ceil(n * R_hat).astype(np.int64)
    bentkus = np.e * binom.cdf(k, n, alpha_dagger)

    return np.minimum(hoeff, bentkus)
