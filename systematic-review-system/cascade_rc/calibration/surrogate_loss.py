"""Vectorised dominating loss tensor for CASCADE-RC calibration (§4).

Loss formula (Mondrian-on-Y=1, evaluated on positives):
    L̃(θ; s, u) = 1{s < λ_lo}  |  (1{λ_lo ≤ s < λ_hi} & 1{u ≥ τ_SE})
with θ = (λ_lo, λ_hi, τ_SE).
"""
from __future__ import annotations

import numpy as np


def breakpoints(K: int, s_values: np.ndarray | None = None) -> np.ndarray:
    """Return the sorted, deduplicated 1-D λ breakpoints used by grid().

    Safe to call with K=1000 even on score-squashed datasets.
    Does NOT allocate the O(K^3) meshgrid — only an O(K) quantile array.
    Always includes 0.0 and 1.0.

    Args:
        K:        Number of quantile points.
        s_values: Optional 1-D score array; when None returns linspace(0,1,K).

    Returns:
        1-D float64 array of unique, sorted breakpoints in [0, 1].
    """
    if s_values is not None:
        pts = np.quantile(np.asarray(s_values, dtype=np.float64),
                          np.linspace(0.0, 1.0, K))
        return np.sort(np.unique(np.append(pts, [0.0, 1.0])))
    return np.linspace(0.0, 1.0, K)


def grid(K: int, s_values: np.ndarray | None = None, K_tau: int | None = None) -> np.ndarray:
    """Return a grid on [0,1]^3 with λ_lo ≤ λ_hi enforced.

    Args:
        K:        Number of breakpoints for λ_lo and λ_hi dimensions.
        s_values: Optional 1-D array of s-scores (e.g. all calibration docs).
                  When provided, λ_lo and λ_hi breakpoints are taken from the
                  K evenly-spaced quantiles of s_values so that each step moves
                  roughly 1/K of the corpus across the threshold boundary.
                  τ_SE always stays uniform on [0, 1].
                  When None (default): falls back to the original uniform grid
                  on [0, 1] for backward compatibility.
                  NOTE: τ_SE is traversed DESC in the S→R walk (τ_SE=1.0 is
                  the safe corner; τ_SE=0.0 is the risky corner).
        K_tau:    Number of breakpoints for τ_SE dimension. Defaults to K when
                  None. Set smaller than K (e.g. 5) to reduce total grid size
                  from K^3 to K^2 * K_tau without sacrificing λ resolution.

    Returns:
        Array of shape (G, 3) where each row is (λ_lo, λ_hi, τ_SE)
        and G ≤ K^2 * K_tau (rows violating λ_lo > λ_hi are dropped).
    """
    lo_vals = hi_vals = breakpoints(K, s_values)
    tau_vals = np.linspace(0.0, 1.0, K_tau if K_tau is not None else K)
    lo, hi, tau = np.meshgrid(lo_vals, hi_vals, tau_vals, indexing="ij")
    points = np.stack([lo.ravel(), hi.ravel(), tau.ravel()], axis=1)
    mask = points[:, 0] <= points[:, 1]
    return points[mask]


def loss_tensor(
    theta_grid: np.ndarray,
    s_pos: np.ndarray,
    u_pos: np.ndarray,
) -> np.ndarray:
    """Compute the dominating loss for every (θ, positive example) pair.

    Args:
        theta_grid: (G, 3) array of (λ_lo, λ_hi, τ_SE) candidates.
        s_pos:      (n_pos,) relevance scores for positive examples (y=1).
        u_pos:      (n_pos,) second-screener scores for the same examples.

    Returns:
        Boolean array of shape (G, n_pos) cast to uint8 {0, 1}.
        Entry [g, i] = 1 when θ_g incurs a loss on example i.
    """
    lam_lo = theta_grid[:, 0:1]   # (G, 1)
    lam_hi = theta_grid[:, 1:2]   # (G, 1)
    tau_se = theta_grid[:, 2:3]   # (G, 1)

    s = s_pos[np.newaxis, :]      # (1, n_pos)
    u = u_pos[np.newaxis, :]      # (1, n_pos)

    # Two disjoint indicator components (see paper §4, Lemma 6)
    term1 = s < lam_lo                                    # rejected below low threshold
    term2 = (lam_lo <= s) & (s < lam_hi) & (u >= tau_se) # uncertain zone, 2nd screener fires

    return (term1 | term2).view(np.uint8)


def slack_tensor(
    theta_grid: np.ndarray,
    s_pos: np.ndarray,
    u_pos: np.ndarray,
    y_hat_pos: np.ndarray,
) -> np.ndarray:
    """Slack η_i(θ) = L̃_i(θ) − L_i(θ) for each (grid point, calibration positive).

    η_i = 1 iff paper is in the uncertain zone, the second screener fires,
    and the LLM verdict was correct (y_hat==1). Zero otherwise (Lemma 1).

    Args:
        theta_grid: (G, 3) array of (λ_lo, λ_hi, τ_SE) candidates.
        s_pos:      (n_pos,) relevance scores for positive examples.
        u_pos:      (n_pos,) second-screener scores for the same examples.
        y_hat_pos:  (n_pos,) LLM verdicts (1 = include, 0 = exclude).

    Returns:
        uint8 array of shape (G, n_pos); entry [g, i] = 1 when η_i(θ_g) = 1.
    """
    lam_lo = theta_grid[:, 0:1]          # (G, 1)
    lam_hi = theta_grid[:, 1:2]          # (G, 1)
    tau_se = theta_grid[:, 2:3]          # (G, 1)

    s = s_pos[np.newaxis, :]             # (1, n_pos)
    u = u_pos[np.newaxis, :]             # (1, n_pos)
    y_hat = y_hat_pos[np.newaxis, :]     # (1, n_pos)

    in_uncertain = (lam_lo <= s) & (s < lam_hi)   # (G, n_pos)
    se_fires = u >= tau_se                          # (G, n_pos)
    llm_correct = y_hat == 1                        # (1, n_pos)

    return (in_uncertain & se_fires & llm_correct).view(np.uint8)
