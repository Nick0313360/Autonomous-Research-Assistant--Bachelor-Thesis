"""Tests for main_calibrate.py — Algorithm 1 orchestration.

All tests use cascade_rc.synthetic.beta_mixture for deterministic, reproducible data.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cascade_rc.config import CascadeRCConfig, LTTBudget
from cascade_rc.synthetic.beta_mixture import generate_paper_running_example


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_config(artefact_dir: Path) -> CascadeRCConfig:
    return CascadeRCConfig(
        ltt=LTTBudget(
            alpha=0.10,
            delta_total=0.10,
            delta_eta=0.03,
            delta_LTT=0.07,
            K=20,
        ),
        artefact_dir=artefact_dir,
    )


def _make_calib_parquet(tmp_path: Path, n: int = 10_000, seed: int = 0) -> Path:
    """Generate synthetic data and write a calibration parquet."""
    df = generate_paper_running_example(n=n, seed=seed)
    df = df.rename(columns={"y": "y_abstract"})

    # Stratified 50/50 split
    rng = np.random.default_rng(20260429)
    is_calib = np.zeros(len(df), dtype=int)
    for label in [0, 1]:
        idx = df.index[df["y_abstract"] == label].tolist()
        calib_idx = rng.choice(idx, size=len(idx) // 2, replace=False)
        is_calib[calib_idx] = 1
    df["is_calib"] = is_calib

    parquet_path = tmp_path / "synthetic.parquet"
    df.to_parquet(parquet_path, index=False)
    return parquet_path


# ---------------------------------------------------------------------------
# test_abstention_when_m_plus_below_N_min
# ---------------------------------------------------------------------------

def test_abstention_when_m_plus_below_N_min(tmp_path: Path) -> None:
    """With m_plus=20 < N_min=26 (α=0.10, δ_LTT=0.07), calibrate() abstains.

    N_min = ceil(ln(1/0.07) / (-ln(1-0.10))) = ceil(25.24) = 26.
    We construct a parquet with exactly 20 positive calibration rows.
    """
    from cascade_rc.calibration.main_calibrate import calibrate

    df = generate_paper_running_example(n=2_000, seed=7)
    df = df.rename(columns={"y": "y_abstract"})

    # Force exactly 20 positives in the calibration set
    pos_idx = df.index[df["y_abstract"] == 1].tolist()
    neg_idx = df.index[df["y_abstract"] == 0].tolist()

    is_calib = np.zeros(len(df), dtype=int)
    for i in pos_idx[:20]:
        is_calib[i] = 1
    for i in neg_idx[:200]:
        is_calib[i] = 1
    df["is_calib"] = is_calib

    parquet_path = tmp_path / "small.parquet"
    df.to_parquet(parquet_path, index=False)

    cfg = _make_config(tmp_path)
    result = calibrate("small", parquet_path, cfg)

    assert isinstance(result, tuple), "should return 3-tuple on abstention"
    none_a, none_b, reason = result
    assert none_a is None
    assert none_b is None
    assert reason.startswith("abstained:m_plus=20"), f"unexpected reason: {reason}"


# ---------------------------------------------------------------------------
# test_certification_synthetic
# ---------------------------------------------------------------------------

def test_certification_synthetic(tmp_path: Path) -> None:
    """Synthetic running example (n=10_000, seed=0) certifies non-empty Λ̂ for α=0.10.

    θ̂ is pinned to the value computed on first correct run.
    Reference computed 2026-05-01 with K=20, seed=0, split_seed=20260429.
    Tolerance: ±1 grid step per axis (atol = 1/(K-1) ≈ 0.0526).
    """
    from cascade_rc.calibration.main_calibrate import calibrate
    from cascade_rc.certificates.store import CertificationResult

    calib_parquet = _make_calib_parquet(tmp_path)
    cfg = _make_config(tmp_path)
    result = calibrate("synthetic", calib_parquet, cfg)

    assert isinstance(result, CertificationResult)
    assert result.status == "certified"
    assert result.lambda_hat_mask.sum() > 0, "Λ̂ must be non-empty"

    # Reference θ̂ computed 2026-05-01, seed=0, K=20, split_seed=20260429
    # Updated 2026-05-08: corrected cost function now includes auto-include overhead
    REFERENCE_THETA_HAT = np.array([0.0, 0.5884308538885089, 0.0])
    np.testing.assert_allclose(result.theta_hat, REFERENCE_THETA_HAT, atol=1.0 / 19)


# ---------------------------------------------------------------------------
# test_resume_from_partial
# ---------------------------------------------------------------------------

def test_resume_from_partial(tmp_path: Path) -> None:
    """Restarting from a partial checkpoint produces bytes-identical Λ̂.

    Strategy:
    1. Run calibrate() fully (no-checkpoint baseline) → result_full.
    2. Manually construct a partial checkpoint from the first 500 eta_lcb values
       of result_full (simulating a run interrupted after 500 grid evaluations).
    3. Run calibrate() on a fresh topic that sees the planted partial → result_resumed.
    4. Assert lambda_hat_mask bytes-identical between result_full and result_resumed.
    """
    from cascade_rc.calibration.main_calibrate import calibrate
    from cascade_rc.calibration.surrogate_loss import grid as sg
    from cascade_rc.certificates.store import CertificateStore

    calib_parquet = _make_calib_parquet(tmp_path)
    cfg = _make_config(tmp_path)

    G = len(sg(cfg.ltt.K))
    # Step 1: Full run (large chunk so no real checkpoints, clean baseline)
    result_full = calibrate("topic_full", calib_parquet, cfg, chunk_size=G + 1)

    # Step 2: Plant partial checkpoint at grid index 500 for "topic_resume"
    partial_state = {
        "grid_idx_completed": min(500, G),
        "eta_lcb_partial": result_full.eta_lcb_grid[: min(500, G)].copy(),
    }
    CertificateStore.save_partial("topic_resume", partial_state, tmp_path)

    # Step 3: Resume run — should skip indices 0:500 and compute the rest
    result_resumed = calibrate("topic_resume", calib_parquet, cfg, chunk_size=G + 1)

    # Step 4: Λ̂ must be bytes-identical
    assert result_resumed.lambda_hat_mask.tobytes() == result_full.lambda_hat_mask.tobytes(), (
        "Resumed Λ̂ differs from full run — checkpointing is broken"
    )


# ---------------------------------------------------------------------------
# test_calibrate_normalize_base_scores
# ---------------------------------------------------------------------------

def _make_squashed_parquet(tmp_path: Path) -> Path:
    """Write a synthetic parquet with s ∈ [0.011, 0.032] to tmp_path."""
    rng = np.random.default_rng(42)
    n = 300
    # Three-way split: is_split=0 (60), is_split=1 (150), is_split=2 (90)
    is_split = np.array([0] * 60 + [1] * 150 + [2] * 90, dtype=np.int8)
    y = np.zeros(n, dtype=np.int64)
    # Place 12 positives in split-0, 30 in split-1, 18 in split-2
    y[:12] = 1
    y[60:90] = 1
    y[210:228] = 1

    df = pd.DataFrame({
        "pmid": [str(i) for i in range(n)],
        "s": rng.uniform(0.011, 0.032, n),  # squashed range
        "u": rng.uniform(0.0, 1.0, n),
        "y_abstract": y,
        "llm_y_hat": rng.integers(0, 2, n, dtype=np.int64),
        "is_split": is_split,
    })
    path = tmp_path / "CD_synthetic.parquet"
    df.to_parquet(path, index=False)
    return path


def test_calibrate_config_snapshot_contains_normalize_flag(tmp_path: Path) -> None:
    """calibrate() persists normalize_base_scores in config_snapshot."""
    from cascade_rc.calibration.main_calibrate import calibrate

    parquet_path = _make_squashed_parquet(tmp_path)

    cfg = CascadeRCConfig(
        normalize_base_scores=True,
        n_jobs_calib=1,
        ltt=LTTBudget(
            alpha=0.10,
            delta_total=0.10,
            delta_eta=0.03,
            delta_LTT=0.07,
            K=3,
            B=3,
            ensemble_temperature=0.7,
            c_human=5.0,
            c_llm=0.001,
            delta_bootstrap=0.05,
        ),
    )

    result = calibrate(
        topic_id="CD_synthetic",
        calib_parquet=parquet_path,
        config=cfg,
        artefact_dir=tmp_path,
    )

    # Must not abstain — we have 30 positives in is_split==1 which exceeds N_min=26
    assert not isinstance(result, tuple), (
        f"calibrate() abstained unexpectedly: {result}"
    )
    assert result.config_snapshot["normalize_base_scores"] is True
