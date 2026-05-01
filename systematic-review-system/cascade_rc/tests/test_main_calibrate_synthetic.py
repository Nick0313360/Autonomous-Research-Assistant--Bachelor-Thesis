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
