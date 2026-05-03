"""Tests for Hoeffding-Bentkus hybrid p-value (cascade_rc/calibration/hb_pvalue.py).

TDD RED phase — written before implementation exists.
"""
from __future__ import annotations

import numpy as np
import pytest

from cascade_rc.calibration.hb_pvalue import hb_pvalue_scalar, hb_pvalues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hoeffding_pvalue(R_hat: np.ndarray, alpha_dagger: np.ndarray, n: int) -> np.ndarray:
    """Plain Hoeffding KL piece only (no Bentkus), for comparison."""
    a = np.minimum(R_hat, alpha_dagger)
    with np.errstate(divide="ignore", invalid="ignore"):
        term1 = np.where(a > 0.0, a * np.log(a / alpha_dagger), 0.0)
        term2 = np.where(alpha_dagger < 1.0,
                         (1.0 - a) * np.log((1.0 - a) / (1.0 - alpha_dagger)),
                         0.0)
    h1 = term1 + term2
    return np.exp(-n * h1)


# ---------------------------------------------------------------------------
# test_hb_super_uniform_under_null
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("q", [0.05, 0.10, 0.20])
def test_hb_super_uniform_under_null(q: float) -> None:
    """p_HB is super-uniform under H₀ at boundary: Pr(p_HB ≤ q) ≤ q.

    Simulation: R̂ ~ Bin(n, α†)/n with n=200, α†=0.1, over 100 000 trials.
    Tolerance of 0.01 covers ~5 sigma Monte-Carlo noise.
    """
    rng = np.random.default_rng(42)
    n = 200
    alpha = 0.1
    n_trials = 100_000
    tol = 0.01

    k_draws = rng.binomial(n, alpha, size=n_trials)
    R_hats = k_draws / n
    alpha_daggered = np.full(n_trials, alpha)

    p_vals = hb_pvalues(R_hats, alpha_daggered, n)
    frac = float(np.mean(p_vals <= q))

    assert frac <= q + tol, (
        f"Super-uniformity violated for q={q}: "
        f"Pr(p_HB ≤ {q}) = {frac:.4f} > {q} + tol={tol}"
    )


# ---------------------------------------------------------------------------
# test_hb_tighter_than_hoeffding
# ---------------------------------------------------------------------------

def test_hb_tighter_than_hoeffding() -> None:
    """Mean p_HB ≤ mean plain-Hoeffding p over 100 000 null trials.

    p_HB = min(Hoeffding, Bentkus) ≤ Hoeffding by definition.
    """
    rng = np.random.default_rng(7)
    n = 200
    alpha = 0.1
    n_trials = 100_000

    k_draws = rng.binomial(n, alpha, size=n_trials)
    R_hats = k_draws / n
    alpha_daggered = np.full(n_trials, alpha)

    p_hb = hb_pvalues(R_hats, alpha_daggered, n)
    p_hoeff = _hoeffding_pvalue(R_hats, alpha_daggered, n)

    assert float(np.mean(p_hb)) <= float(np.mean(p_hoeff)), (
        f"Mean p_HB {np.mean(p_hb):.6f} > mean Hoeffding {np.mean(p_hoeff):.6f}"
    )


# ---------------------------------------------------------------------------
# test_hb_scalar_matches_vectorised
# ---------------------------------------------------------------------------

def test_hb_scalar_matches_vectorised() -> None:
    """hb_pvalue_scalar and hb_pvalues agree for a range of R̂ values."""
    rng = np.random.default_rng(99)
    n = 100
    alpha = 0.15
    R_hats = rng.uniform(0.0, 0.3, size=20)
    alpha_daggered = np.full(20, alpha)

    vec = hb_pvalues(R_hats, alpha_daggered, n)
    scalars = np.array([hb_pvalue_scalar(float(r), alpha, n) for r in R_hats])

    np.testing.assert_allclose(vec, scalars, rtol=1e-9)
