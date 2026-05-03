"""Predictable-plug-in betting lower confidence bounds (CASCADE-RC §5.2).

Provides:
- wsr_lcb_one_sided  — per-sample LCB via Waudby-Smith & Ramdas (2024) betting CS
- wsr_lcb_grid       — vectorised Bonferroni-corrected LCB over a calibration grid

References:
  Waudby-Smith & Ramdas (2024), "Estimating means of bounded random variables
  by betting", JRSS-B.  arXiv:2010.09686
  Shekhar & Ramdas (2024), arXiv:2310.01547
"""
from __future__ import annotations

from typing import Literal

import numpy as np
from confseq.betting import betting_lower_cs, lambda_predmix_eb
from joblib import Parallel, delayed


def _ons_lambda(x: np.ndarray, m: float) -> np.ndarray:
    """Online Newton Step betting strategy for [0,1]-bounded observations.

    Implements the ONS bet sequence: λ_t = clamp(ĝ_t / Ĝ_t, 0, trunc)
    where ĝ_t is the sum of subgradients and Ĝ_t is the sum of squared
    subgradients (diagonal ONS with identity prior).
    """
    n = len(x)
    lambdas = np.empty(n)
    g_sum = 0.0
    g2_sum = 1.0  # regulariser to avoid division by zero at t=1
    for i in range(n):
        lam = np.clip(g_sum / g2_sum, 0.0, 0.5)
        lambdas[i] = lam
        grad = x[i] - m
        g_sum += grad
        g2_sum += grad * grad
    return lambdas


def wsr_lcb_one_sided(
    samples: np.ndarray,
    delta: float,
    strategy: Literal["prpl", "ons"] = "prpl",
) -> float:
    """Return the time-uniform one-sided lower confidence bound at level 1-delta.

    Uses the betting confidence sequence of Waudby-Smith & Ramdas (2024).
    A one-sided bound is obtained by calling the two-sided CS with
    alpha = 2*delta and taking the lower endpoint (Bonferroni argument).

    Args:
        samples:  (n,) array of slack values in [0, 1].
        delta:    Miscoverage level for this single grid point.
        strategy: "prpl" (predictable plug-in, default) or "ons".

    Returns:
        Scalar lower confidence bound ≥ 0.
    """
    alpha_two_sided = 2.0 * delta

    if strategy == "prpl":
        lambdas_fn = None  # default in betting_lower_cs is PrPl (lambda_predmix_eb)
    else:
        lambdas_fn = [lambda x, m: _ons_lambda(x, m)]  # noqa: E731

    lo = betting_lower_cs(
        samples,
        lambdas_fns=lambdas_fn,
        alpha=alpha_two_sided,
        running_intersection=True,
        breaks=200,  # 200 vs default 1000: same bound at ~5x speedup
    )
    return float(max(lo[-1], 0.0))


def wsr_lcb_grid(
    slack_samples: np.ndarray,
    delta_eta: float,
    num_grid_points: int,
) -> np.ndarray:
    """Bonferroni-corrected LCB for every point on the calibration grid.

    Each grid point receives an individual level of delta_eta / num_grid_points
    (Bonferroni union bound over |Λ| tests).

    Args:
        slack_samples:   (num_grid_points, n) array; row g holds the n slack
                         samples collected at grid point g.
        delta_eta:       Total miscoverage budget for η across the grid.
        num_grid_points: |Λ| — number of grid points (== slack_samples.shape[0]).

    Returns:
        (num_grid_points,) array of lower confidence bounds η̂⁻(θ).
    """
    per_point_delta = delta_eta / num_grid_points

    lcbs: list[float] = Parallel(n_jobs=-1)(
        delayed(wsr_lcb_one_sided)(slack_samples[g], delta=per_point_delta)
        for g in range(num_grid_points)
    )
    return np.array(lcbs, dtype=np.float64)
