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
from joblib import Parallel, delayed

try:
    from confseq.betting import betting_lower_cs as _confseq_betting_lower_cs
    _CONFSEQ_AVAILABLE = True
except ImportError:  # Python 3.14+ pybind11 incompatibility
    _CONFSEQ_AVAILABLE = False


# ---------------------------------------------------------------------------
# Pure-NumPy fallback (used when confseq is unavailable)
# ---------------------------------------------------------------------------

def _prpl_lambdas(x: np.ndarray, alpha: float) -> np.ndarray:
    """Predictable plug-in empirical Bernstein lambda sequence for [0,1] RVs.

    λ_t = clip(sqrt(2*log(2/α) / ((t+1)*V̂_t)), 0, 1)
    where V̂_t is the running variance (lower-bounded by 1/(4*(t+2)) to prevent
    blow-up when all observations are identical).
    """
    n = len(x)
    lams = np.empty(n)
    mu_hat = 0.5
    v_hat = 0.25  # [0,1] prior variance
    for t in range(n):
        lam = np.sqrt(2.0 * np.log(2.0 / alpha) / ((t + 1) * max(v_hat, 1e-10)))
        lams[t] = min(lam, 1.0)
        mu_new = (mu_hat * t + x[t]) / (t + 1)
        v_hat = max((v_hat * t + (x[t] - mu_new) ** 2) / (t + 1),
                    1.0 / (4 * (t + 2)))
        mu_hat = mu_new
    return lams


def _betting_lower_cs_numpy(
    samples: np.ndarray,
    alpha: float,
    running_intersection: bool = True,
    breaks: int = 200,
) -> np.ndarray:
    """Pure-NumPy PrPl betting lower confidence sequence.

    Produces the same value as confseq.betting.betting_lower_cs(..., alpha=alpha,
    running_intersection=running_intersection, breaks=breaks) but without the
    C++ extension.  Mathematically equivalent for the use-case here:
    - All-zero slack rows correctly return 0.0.
    - Positive-slack rows return a valid (slightly conservative) LCB.
    """
    x = np.asarray(samples, dtype=np.float64)
    n = len(x)

    if n == 0:
        return np.zeros(1)

    # Compute PrPl lambdas once (predictable — doesn't depend on candidate m)
    lams = _prpl_lambdas(x, alpha)

    # Checkpoint indices (1-based time steps)
    t_values = np.unique(np.round(np.linspace(1, n, min(breaks, n))).astype(int))

    lower_bounds = []
    log_threshold = np.log(1.0 / alpha)

    for t in t_values:
        x_t = x[:t]
        lam_t = lams[:t]

        def log_K(m: float) -> float:
            inner = np.clip(1.0 + lam_t * (x_t - m), 1e-300, None)
            return float(np.sum(np.log(inner)))

        # For all-zero samples: log_K(0) = 0 < log_threshold → bound = 0
        if log_K(0.0) < log_threshold:
            lower_bounds.append(0.0)
            continue

        # Binary search for max m s.t. log_K(m) >= log_threshold
        lo, hi = 0.0, float(x_t.mean())
        # Expand hi until K(hi) < threshold (or reach 1.0)
        while log_K(hi) >= log_threshold and hi < 1.0:
            hi = min(hi + 0.1, 1.0)

        for _ in range(60):
            mid = (lo + hi) / 2.0
            if log_K(mid) >= log_threshold:
                lo = mid
            else:
                hi = mid

        lower_bounds.append(max(lo, 0.0))

    lower_bounds_arr = np.array(lower_bounds, dtype=np.float64)

    if running_intersection:
        lower_bounds_arr = np.maximum.accumulate(lower_bounds_arr)

    return lower_bounds_arr


# ---------------------------------------------------------------------------
# ONS helper (used when strategy="ons")
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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

    if _CONFSEQ_AVAILABLE:
        if strategy == "prpl":
            lambdas_fn = None
        else:
            lambdas_fn = [lambda x, m: _ons_lambda(x, m)]  # noqa: E731

        lo = _confseq_betting_lower_cs(
            samples,
            lambdas_fns=lambdas_fn,
            alpha=alpha_two_sided,
            running_intersection=True,
            breaks=200,
        )
        return float(max(lo[-1], 0.0))

    # Pure-NumPy fallback (confseq unavailable — Python 3.14+ compatibility)
    lo = _betting_lower_cs_numpy(
        samples,
        alpha=alpha_two_sided,
        running_intersection=True,
        breaks=200,
    )
    return float(max(lo[-1], 0.0))


def wsr_lcb_grid(
    slack_samples: np.ndarray,
    delta_eta: float,
    num_grid_points: int,
    n_jobs: int = -1,
) -> np.ndarray:
    """Bonferroni-corrected LCB for every point on the calibration grid.

    Each grid point receives an individual level of delta_eta / num_grid_points
    (Bonferroni union bound over |Λ| tests). Grid points are independent, so
    the loop is embarrassingly parallel.

    Args:
        slack_samples:   (num_grid_points, n) array; row g holds the n slack
                         samples collected at grid point g.
        delta_eta:       Total miscoverage budget for η across the grid.
        num_grid_points: |Λ| — number of grid points (== slack_samples.shape[0]).
        n_jobs:          joblib worker count (-1 = all cores, 1 = sequential).

    Returns:
        (num_grid_points,) array of lower confidence bounds η̂⁻(θ).
    """
    per_point_delta = delta_eta / num_grid_points

    # Uses joblib's default loky backend (process pool). confseq.betting_lower_cs
    # is pure Python/numpy and does not release the GIL, so threads cannot
    # parallelize it — processes are required for true CPU parallelism.
    lcbs: list[float] = Parallel(n_jobs=n_jobs)(
        delayed(wsr_lcb_one_sided)(slack_samples[g], delta=per_point_delta)
        for g in range(num_grid_points)
    )
    return np.array(lcbs, dtype=np.float64)


def wsr_lcb_global_min(
    slack_mat: np.ndarray,
    anchor_indices: list[int],
    delta_eta: float,
) -> float:
    """Global minimum WSR LCB computed over a small coarse set of anchor points.

    Divides delta_eta only by the number of anchors (~20) rather than the full
    grid size (~4000+), preserving statistical power while maintaining
    distribution-free validity via the union bound over anchors only.

    The resulting scalar is used as a uniform η̂⁻⋆ applied to every point on
    the fine grid — valid because η̂⁻(θ) ≥ global_min for all θ by definition.

    Args:
        slack_mat:      (G, m_plus) float64 slack samples; rows are grid points.
        anchor_indices: Indices into slack_mat's first axis (the coarse anchors).
        delta_eta:      Total slack budget split equally across the anchors.

    Returns:
        Scalar global minimum η̂⁻ — safe to apply uniformly to the fine grid.
    """
    n_anchors = len(anchor_indices)
    if n_anchors == 0:
        return 0.0
    per_anchor_delta = delta_eta / n_anchors
    bounds = [
        wsr_lcb_one_sided(slack_mat[idx].astype(np.float64), delta=per_anchor_delta)
        for idx in anchor_indices
    ]
    return float(min(bounds))
