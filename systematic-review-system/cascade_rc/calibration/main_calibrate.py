"""Algorithm 1 orchestrator for CASCADE-RC calibration (paper §5.4).

Entry point:
    python -m cascade_rc.calibration.main_calibrate --topic CD008874 --calib-parquet path/to/file.parquet
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from cascade_rc.calibration.hb_pvalue import hb_pvalues
from cascade_rc.calibration.surrogate_loss import grid as _theta_grid, loss_tensor, slack_tensor
from cascade_rc.calibration.walker import safest_to_riskiest_order, walk_reject
from cascade_rc.calibration.wsr_lcb import wsr_lcb_one_sided
from cascade_rc.certificates.store import CertificationResult, CertificateStore
from cascade_rc.config import CascadeRCConfig


def _compute_n_min(alpha: float, delta_ltt: float) -> int:
    """N_min = ceil(ln(1/δ_LTT) / (-ln(1-α))) — minimum calibration positives required."""
    return math.ceil(math.log(1.0 / delta_ltt) / (-math.log(1.0 - alpha)))


def _expected_cost(
    theta_grid: np.ndarray,
    s_all: np.ndarray,
    u_all: np.ndarray,
    c_human: float,
    c_llm: float,
) -> np.ndarray:
    """Expected operating cost for each grid point (§6).

    Cost = c_human * P(uncertain zone, SE silent) + c_llm * P(uncertain zone, SE fires).

    Args:
        theta_grid: (G, 3) grid of (λ_lo, λ_hi, τ_SE).
        s_all:      (N,) relevance scores for all is_calib==1 rows.
        u_all:      (N,) second-screener scores for the same rows.
        c_human:    Cost of human review.
        c_llm:      Cost of LLM/SE escalation.

    Returns:
        (G,) array of expected costs.
    """
    lam_lo = theta_grid[:, 0:1]   # (G, 1)
    lam_hi = theta_grid[:, 1:2]   # (G, 1)
    tau_se = theta_grid[:, 2:3]   # (G, 1)

    s = s_all[np.newaxis, :]      # (1, N)
    u = u_all[np.newaxis, :]      # (1, N)

    in_uncertain = (lam_lo <= s) & (s < lam_hi)    # (G, N)
    se_fires = u >= tau_se                           # (G, N)

    p_no_se = (in_uncertain & ~se_fires).mean(axis=1)   # (G,)
    p_se = (in_uncertain & se_fires).mean(axis=1)        # (G,)

    return c_human * p_no_se + c_llm * p_se             # (G,)


def _compute_eta_lcb_chunked(
    slack_mat: np.ndarray,
    delta_eta: float,
    G: int,
    topic: str,
    artefact_dir: Path,
    chunk_size: int = 500,
    resume_from: int = 0,
    resume_eta_lcb: np.ndarray | None = None,
) -> np.ndarray:
    """Compute η̂⁻⋆(θ) for all G grid points with chunked checkpointing.

    Bonferroni level is delta_eta / G regardless of chunk size.
    Every chunk_size evaluations, state is saved to <topic>.partial.pkl.

    Args:
        slack_mat:       (G, m_plus) float64 slack samples.
        delta_eta:       Total slack budget across all grid points.
        G:               Total number of grid points (for Bonferroni).
        topic:           Topic identifier for partial checkpoint naming.
        artefact_dir:    Directory for partial checkpoints.
        chunk_size:      Grid points per checkpoint batch.
        resume_from:     First uncompleted grid index (0 = start fresh).
        resume_eta_lcb:  (G,) array pre-filled for indices < resume_from.

    Returns:
        (G,) array of η̂⁻⋆ values.
    """
    eta_lcb = resume_eta_lcb if resume_eta_lcb is not None else np.zeros(G)
    per_point_delta = delta_eta / G  # Bonferroni over all G points

    for start in range(resume_from, G, chunk_size):
        end = min(start + chunk_size, G)
        chunk_indices = list(range(start, end))
        chunk_lcbs: list[float] = Parallel(n_jobs=-1)(
            delayed(wsr_lcb_one_sided)(
                slack_mat[g].astype(np.float64), delta=per_point_delta
            )
            for g in chunk_indices
        )
        eta_lcb[start:end] = chunk_lcbs
        state = {
            "grid_idx_completed": end,
            "eta_lcb_partial": eta_lcb[:end].copy(),
        }
        CertificateStore.save_partial(topic, state, artefact_dir)

    return eta_lcb


def calibrate(
    topic_id: str,
    calib_parquet: Path,
    config: CascadeRCConfig,
    artefact_dir: Path | None = None,
    chunk_size: int = 500,
) -> "CertificationResult | tuple[None, None, str]":
    """Run Algorithm 1: certify operating point θ̂ for topic_id.

    Args:
        topic_id:       Topic identifier used for artefact naming.
        calib_parquet:  Parquet with columns: pmid, s, u, y_abstract, llm_y_hat, is_calib.
        config:         CascadeRCConfig with LTT budget and artefact paths.
        artefact_dir:   Override for config.artefact_dir.
        chunk_size:     Grid points per WSR checkpoint batch (default 500).

    Returns:
        CertificationResult on success, or (None, None, reason_str) on abstention.
    """
    if artefact_dir is None:
        artefact_dir = config.artefact_dir

    ltt = config.ltt
    alpha = ltt.alpha
    delta_eta = ltt.delta_eta
    delta_ltt = ltt.delta_LTT
    K = ltt.K
    c_human = ltt.c_human
    c_llm = ltt.c_llm

    # Step 1: Filter calibration positives
    df = pd.read_parquet(calib_parquet)
    df_pos = df[(df["is_calib"] == 1) & (df["y_abstract"] == 1)]
    m_plus = len(df_pos)

    # Step 2: Abstention check
    N_min = _compute_n_min(alpha, delta_ltt)
    if m_plus < N_min:
        return (None, None, f"abstained:m_plus={m_plus}<{N_min}")

    s_pos = df_pos["s"].to_numpy(dtype=np.float64)
    u_pos = df_pos["u"].to_numpy(dtype=np.float64)
    y_hat_pos = df_pos["llm_y_hat"].to_numpy(dtype=np.int64)

    df_calib = df[df["is_calib"] == 1]
    s_all = df_calib["s"].to_numpy(dtype=np.float64)
    u_all = df_calib["u"].to_numpy(dtype=np.float64)

    # Step 3: Build K^3 grid (filtered to λ_lo ≤ λ_hi)
    theta_g = _theta_grid(K)    # (G, 3)
    G = len(theta_g)

    # Step 4: Loss and slack matrices (G, m_plus)
    loss_mat = loss_tensor(theta_g, s_pos, u_pos).astype(np.float64)
    slack_mat = slack_tensor(theta_g, s_pos, u_pos, y_hat_pos).astype(np.float64)

    # Resume from partial checkpoint if it exists
    partial = CertificateStore.load_partial(topic_id, artefact_dir)
    resume_from = 0
    resume_eta_lcb: np.ndarray | None = None
    if partial is not None:
        resume_from = partial["grid_idx_completed"]
        padded = np.zeros(G)
        stored = partial["eta_lcb_partial"]
        padded[: len(stored)] = stored
        resume_eta_lcb = padded

    # Compute η̂⁻⋆ with checkpointing
    eta_lcb = _compute_eta_lcb_chunked(
        slack_mat, delta_eta, G, topic_id, artefact_dir,
        chunk_size=chunk_size, resume_from=resume_from, resume_eta_lcb=resume_eta_lcb,
    )

    # Step 5: Empirical risk R̂(θ)
    R_hat = loss_mat.mean(axis=1)    # (G,)

    # Step 6: Corrected level α†(θ) = α + η̂⁻⋆(θ)
    alpha_dagger = alpha + eta_lcb   # (G,)

    # Step 7: HB p-values
    p_hb = hb_pvalues(R_hat, alpha_dagger, n=m_plus)   # (G,)

    # Step 8: Fixed-sequence walk — reject until first acceptance
    order = safest_to_riskiest_order(theta_g)
    lambda_hat_mask = walk_reject(p_hb, order, delta_ltt)   # (G,) bool

    # Step 9: θ̂ = argmin expected_cost over Λ̂
    costs = _expected_cost(theta_g, s_all, u_all, c_human, c_llm)
    certified_costs = np.where(lambda_hat_mask, costs, np.inf)
    theta_hat_idx = int(np.argmin(certified_costs))
    theta_hat = theta_g[theta_hat_idx]

    # Step 10: Persist result and clean up partial
    result = CertificationResult(
        topic=topic_id,
        status="certified",
        abstain_reason=None,
        m_plus=m_plus,
        theta_hat=theta_hat,
        lambda_hat_mask=lambda_hat_mask,
        theta_grid=theta_g,
        eta_lcb_grid=eta_lcb,
        r_hat_grid=R_hat,
        p_hb_grid=p_hb,
        alpha_dagger_grid=alpha_dagger,
        slack_mat=slack_mat,
        config_snapshot={
            "alpha": alpha,
            "delta_eta": delta_eta,
            "delta_LTT": delta_ltt,
            "K": K,
            "c_human": c_human,
            "c_llm": c_llm,
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    CertificateStore.save(topic_id, result, artefact_dir)
    CertificateStore.delete_partial(topic_id, artefact_dir)

    return result


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="CASCADE-RC calibration — Algorithm 1",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", required=True, help="Topic identifier, e.g. CD008874")
    parser.add_argument(
        "--calib-parquet", required=True, type=Path,
        help="Path to calibration parquet (columns: pmid,s,u,y_abstract,llm_y_hat,is_calib)",
    )
    parser.add_argument(
        "--artefact-dir", type=Path, default=None,
        help="Override artefact_dir from config",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=500,
        help="Grid points per WSR checkpoint batch",
    )
    args = parser.parse_args()

    cfg = CascadeRCConfig()

    result = calibrate(
        topic_id=args.topic,
        calib_parquet=args.calib_parquet,
        config=cfg,
        artefact_dir=args.artefact_dir,
        chunk_size=args.chunk_size,
    )

    if isinstance(result, tuple):
        print(f"ABSTAINED: {result[2]}")
        sys.exit(0)

    print(f"CERTIFIED: Λ̂={result.lambda_hat_mask.sum()} points  θ̂={result.theta_hat.tolist()}")
    sys.exit(0)


if __name__ == "__main__":
    main()
