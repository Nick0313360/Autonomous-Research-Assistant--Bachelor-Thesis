"""Algorithm 1 orchestrator for CASCADE-RC calibration (paper §5.4).

Entry point:
    python -m cascade_rc.calibration.main_calibrate --topic CD008874 --calib-parquet path/to/file.parquet
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from cascade_rc.calibration.hb_pvalue import hb_pvalues
from cascade_rc.calibration.surrogate_loss import grid as _theta_grid, loss_tensor, slack_tensor
from cascade_rc.calibration.walker import safest_to_riskiest_order, walk_reject
from cascade_rc.calibration.wsr_lcb import wsr_lcb_one_sided
from cascade_rc.certificates.store import CertificationResult, CertificateStore
from cascade_rc.config import CascadeRCConfig, LTTBudget


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
    """Expected operating cost per document for each grid point (§6).

    Three cost sources across the full corpus:
      1. Auto-include (s >= λ_hi):  sent to full-text human review → c_human each.
      2. Uncertain zone, LLM called (λ_lo <= s < λ_hi): LLM query cost → c_llm each.
      3. Uncertain zone, LLM inconsistent (u < τ_SE): escalated to human → c_human each.
      4. Cheap-reject (s < λ_lo): no cost.

    This replaces the old formulation that only counted uncertain-zone work, which
    made (λ_hi=0) — auto-include everything — appear free despite requiring a human
    to review every document.

    Args:
        theta_grid: (G, 3) grid of (λ_lo, λ_hi, τ_SE).
        s_all:      (N,) relevance scores for all is_calib==1 rows.
        u_all:      (N,) second-screener scores for the same rows.
        c_human:    Cost of human (full-text) review.
        c_llm:      Cost of LLM ensemble call.

    Returns:
        (G,) array of expected costs.
    """
    lam_lo = theta_grid[:, 0:1]   # (G, 1)
    lam_hi = theta_grid[:, 1:2]   # (G, 1)
    tau_se = theta_grid[:, 2:3]   # (G, 1)

    s = s_all[np.newaxis, :]      # (1, N)
    u = u_all[np.newaxis, :]      # (1, N)

    auto_include = s >= lam_hi                         # (G, N)
    in_band      = (s >= lam_lo) & (s < lam_hi)       # (G, N)
    human_review = in_band & (u < tau_se)              # (G, N): LLM inconsistent → human

    p_auto   = auto_include.mean(axis=1)   # (G,)
    p_llm    = in_band.mean(axis=1)        # (G,)
    p_human  = human_review.mean(axis=1)   # (G,)

    return c_human * p_auto + c_llm * p_llm + c_human * p_human   # (G,)


def _compute_eta_lcb_chunked(
    slack_mat: np.ndarray,
    delta_eta: float,
    G: int,
    topic: str,
    artefact_dir: Path,
    chunk_size: int = 500,
    resume_from: int = 0,
    resume_eta_lcb: np.ndarray | None = None,
    n_jobs: int = -1,
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
        n_jobs:          joblib worker count (-1 = all cores, 1 = sequential).

    Returns:
        (G,) array of η̂⁻⋆ values.
    """
    eta_lcb = resume_eta_lcb if resume_eta_lcb is not None else np.zeros(G)
    per_point_delta = delta_eta / G  # Bonferroni over all G points

    for start in range(resume_from, G, chunk_size):
        end = min(start + chunk_size, G)
        chunk_indices = list(range(start, end))
        chunk_lcbs: list[float] = Parallel(n_jobs=n_jobs)(
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
    order_fn: Callable[[np.ndarray], np.ndarray] | None = None,
) -> "CertificationResult | tuple[None, None, str]":
    """Run Algorithm 1: certify operating point θ̂ for topic_id.

    Args:
        topic_id:       Topic identifier used for artefact naming.
        calib_parquet:  Parquet with columns: pmid, s, u, y_abstract, llm_y_hat, is_calib.
        config:         CascadeRCConfig with LTT budget and artefact paths.
        artefact_dir:   Override for config.artefact_dir.
        chunk_size:     Grid points per WSR checkpoint batch (default 500).
        order_fn:       Optional callable that takes the (G, 3) parameter grid and
                        returns a (G,) permutation of indices defining the LTT walk
                        order. Defaults to safest_to_riskiest_order (Lemma 6).
                        Custom orderings are used by cascade_rc.ablations.walk_ordering
                        for empirical validation of Lemma 6.

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
    if config.quantile_scale_base_scores:
        from cascade_rc.data.score_normalizer import quantile_scale_s
        df = quantile_scale_s(df)

    # Backwards-compat shim: old two-way split has 'is_calib' but no 'is_split'
    if "is_split" not in df.columns:
        import warnings
        warnings.warn(
            f"Parquet {calib_parquet} has 'is_calib' but no 'is_split'. "
            "Mapping is_calib==1 → is_split=1 (conformal_calib), "
            "is_calib==0 → is_split=2 (test). "
            "WARNING: no score_calib split (is_split=0) exists — "
            "calibrator was trained on conformal_calib data, violating exchangeability.",
            UserWarning,
            stacklevel=2,
        )
        df = df.copy()
        df["is_split"] = df["is_calib"].map({1: 1, 0: 2}).fillna(2).astype("int8")

    _debug_pos = df[(df["is_split"] == 1) & (df["y_abstract"] == 1)]
    print(f"[DEBUG CALIBRATE] parquet path: {calib_parquet}")
    print(f"[DEBUG CALIBRATE] s range at load time: [{df['s'].min():.4f}, {df['s'].max():.4f}]")
    print(f"[DEBUG CALIBRATE] s on calib positives: [{_debug_pos['s'].min():.4f}, {_debug_pos['s'].max():.4f}]")
    df_pos = _debug_pos
    m_plus = len(df_pos)

    # Step 2: Abstention check
    N_min = _compute_n_min(alpha, delta_ltt)
    if m_plus < N_min:
        return (None, None, f"abstained:m_plus={m_plus}<{N_min}")

    s_pos = df_pos["s"].to_numpy(dtype=np.float64)
    u_pos = df_pos["u"].to_numpy(dtype=np.float64)
    if "llm_y_hat" in df_pos.columns:
        y_hat_pos = df_pos["llm_y_hat"].to_numpy(dtype=np.int64)
    else:
        # Conservative fallback: no LLM verdicts available → zero slack (η=0).
        # This tightens alpha_dagger = alpha (no correction), which may force
        # tau_SE > 0 at strict alpha levels where R̂(tau_SE=0) > alpha.
        y_hat_pos = np.zeros(m_plus, dtype=np.int64)

    print(f"[ALG1] m+ = {m_plus}")
    print(f"[ALG1] s_pos range: [{s_pos.min():.4f}, {s_pos.max():.4f}]")
    print(f"[ALG1] u_pos range: [{u_pos.min():.4f}, {u_pos.max():.4f}]")

    df_calib = df[df["is_split"] == 1]
    s_all = df_calib["s"].to_numpy(dtype=np.float64)
    u_all = df_calib["u"].to_numpy(dtype=np.float64)

    # Step 3: Build quantile-anchored grid (filtered to λ_lo ≤ λ_hi)
    # s_values=s_all ensures each λ step moves ~1/K of the corpus, preventing
    # the walk from dying at the first non-zero step (Bug 1 fix).
    theta_g = _theta_grid(K, s_values=s_all)    # (G, 3)
    G = len(theta_g)

    _grid_breakpoints = np.unique(theta_g[:, 0])
    print(f"[ALG1] λ_lo breakpoints: {np.round(_grid_breakpoints, 4).tolist()}")
    print(f"[ALG1] λ_hi breakpoints: {np.round(np.unique(theta_g[:, 1]), 4).tolist()}")
    print("[ALG1] Fraction of positives below each λ_hi step:")
    for _bp in _grid_breakpoints[:5]:
        print(f"  λ_hi={_bp:.4f}: {(s_pos < _bp).mean():.4f}")

    # Step 4: Loss and slack matrices (G, m_plus)
    loss_mat = loss_tensor(theta_g, s_pos, u_pos).astype(np.float64)
    slack_mat = slack_tensor(theta_g, s_pos, u_pos, y_hat_pos).astype(np.float64)

    _R_hat_preview = loss_mat.mean(axis=1)
    print(f"[ALG1] R_hat range: [{_R_hat_preview.min():.4f}, {_R_hat_preview.max():.4f}]")
    print(f"[ALG1] R_hat at grid[0]: {_R_hat_preview[0]:.4f}")
    print(f"[ALG1] R_hat at grid[-1]: {_R_hat_preview[-1]:.4f}")
    print(f"[ALG1] Fraction of grid with R_hat < alpha={alpha}: {(_R_hat_preview < alpha).mean():.4f}")

    # Bug 2 cost-function verification (scalar spot-checks)
    _cost_000 = float(c_human * 1.0)   # (0,0,0): λ_hi=0 → all auto-include
    _cost_111 = 0.0                    # (1,1,1): λ_lo=1 → all cheap-reject (s<1)
    _th_mid   = np.array([[0.1, 0.5, 0.6]])
    _s_mid    = s_all[np.newaxis, :]
    _u_mid    = u_all[np.newaxis, :]
    _ai_mid   = (_s_mid >= 0.5).mean()
    _ib_mid   = ((_s_mid >= 0.1) & (_s_mid < 0.5)).mean()
    _hr_mid   = ((_s_mid >= 0.1) & (_s_mid < 0.5) & (_u_mid < 0.6)).mean()
    _cost_mid = float(c_human * _ai_mid + c_llm * _ib_mid + c_human * _hr_mid)
    print(f"[ALG1] Cost sanity — (0,0,0): {_cost_000:.4f}  (1,1,1): {_cost_111:.4f}  (0.1,0.5,0.6): {_cost_mid:.4f}")

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
        n_jobs=config.n_jobs_calib,
    )

    # Step 5: Empirical risk R̂(θ)
    R_hat = loss_mat.mean(axis=1)    # (G,)

    # Step 6: Corrected level α†(θ) = α + η̂⁻⋆(θ)
    alpha_dagger = alpha + eta_lcb   # (G,)

    print(f"[ALG1] eta_lcb range (global LCB): [{eta_lcb.min():.6f}, {eta_lcb.max():.6f}]")
    print(f"[ALG1] alpha_dagger range: [{alpha_dagger.min():.6f}, {alpha_dagger.max():.6f}]")

    # Step 7: HB p-values
    p_hb = hb_pvalues(R_hat, alpha_dagger, n=m_plus)   # (G,)

    print(f"[ALG1] p_HB range: [{p_hb.min():.6f}, {p_hb.max():.6f}]")
    print(f"[ALG1] Fraction with p_HB <= delta_LTT={delta_ltt}: {(p_hb <= delta_ltt).mean():.4f}")
    print(f"[ALG1] p_HB at grid[0] (λ_lo=min, λ_hi=min, τ_SE=0): {p_hb[0]:.6f}")

    # Step 8: Fixed-sequence walk — reject until first acceptance
    order = (order_fn if order_fn is not None else safest_to_riskiest_order)(theta_g)
    lambda_hat_mask = walk_reject(p_hb, order, delta_ltt)   # (G,) bool

    _walk_stop = int(lambda_hat_mask.sum())
    _walk_stop_theta = theta_g[order[_walk_stop]] if _walk_stop < len(order) else None
    print(f"[ALG1] |Lambda_hat| = {_walk_stop}")
    print(f"[ALG1] Walk stopped at step {_walk_stop}: first non-certified theta = "
          f"{_walk_stop_theta.tolist() if _walk_stop_theta is not None else 'end-of-walk'}")
    print(f"[ALG1] p_HB at walk-stop theta: "
          f"{p_hb[order[_walk_stop]]:.6f}" if _walk_stop < len(order) else "[ALG1] (full walk completed)")

    # Step 9: θ̂ = argmin expected_cost over Λ̂
    costs = _expected_cost(theta_g, s_all, u_all, c_human, c_llm)
    certified_costs = np.where(lambda_hat_mask, costs, np.inf)
    theta_hat_idx = int(np.argmin(certified_costs))
    theta_hat = theta_g[theta_hat_idx]

    _cert_costs = costs[lambda_hat_mask]
    print(f"[ALG1] Cost values in Lambda_hat: min={_cert_costs.min():.6f}  "
          f"max={_cert_costs.max():.6f}  n_unique={len(np.unique(_cert_costs))}")
    print(f"[ALG1] theta_hat = {theta_hat.tolist()}")

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
            "quantile_scale_base_scores": config.quantile_scale_base_scores,
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    CertificateStore.save(topic_id, result, artefact_dir)
    CertificateStore.delete_partial(topic_id, artefact_dir)

    return result


def run_calibration(
    df: pd.DataFrame,
    topic_id: str,
    alpha: float,
    delta_eta: float,
    delta_ltt: float,
    artefact_dir: Path,
    save_certificate: bool = True,
) -> dict:
    """Run Algorithm 1 from a pre-loaded DataFrame at the given (alpha, delta) values.

    Used by the alpha sweep (alpha_sweep.py) to re-calibrate at each α without
    re-running LLM calls (all decisions are cached in the SQLite ensemble cache).

    When save_certificate=False, a temporary artefact directory is used so the
    headline α=0.10 certificate on disk is never overwritten.

    Returns:
        dict with keys:
          status ("certified" or abstain message string),
          theta_hat (np.ndarray, shape (3,)),
          lambda_hat_size (int),
          eta_lcb_star (float),
          alpha_dagger (float).
    """
    import shutil
    import tempfile

    base_cfg = CascadeRCConfig()
    new_ltt = LTTBudget(
        alpha=alpha,
        delta_eta=delta_eta,
        delta_LTT=delta_ltt,
        delta_total=delta_eta + delta_ltt,
        K=base_cfg.ltt.K,
        B=base_cfg.ltt.B,
        ensemble_temperature=base_cfg.ltt.ensemble_temperature,
        c_human=base_cfg.ltt.c_human,
        c_llm=base_cfg.ltt.c_llm,
        delta_bootstrap=base_cfg.ltt.delta_bootstrap,
    )
    cfg = base_cfg.model_copy(update={"ltt": new_ltt})

    tmpdir: Path | None = None
    if not save_certificate:
        tmpdir = Path(tempfile.mkdtemp(prefix="crc_alpha_sweep_"))
    _artefact_dir = artefact_dir if save_certificate else tmpdir

    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as fh:
        df.to_parquet(fh.name, index=False)
        parquet_path = Path(fh.name)

    try:
        result = calibrate(
            topic_id=topic_id,
            calib_parquet=parquet_path,
            config=cfg,
            artefact_dir=_artefact_dir,
        )

        if isinstance(result, tuple):
            return {"status": result[2]}

        mask = result.lambda_hat_mask
        n_cert = int(mask.sum())
        eta_lcb_star = float(result.eta_lcb_grid[mask].min()) if n_cert > 0 else 0.0
        alpha_dagger = float(result.alpha_dagger_grid[mask].mean()) if n_cert > 0 else 0.0

        return {
            "status": "certified",
            "theta_hat": result.theta_hat,
            "lambda_hat_size": n_cert,
            "eta_lcb_star": eta_lcb_star,
            "alpha_dagger": alpha_dagger,
        }
    finally:
        parquet_path.unlink(missing_ok=True)
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


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
