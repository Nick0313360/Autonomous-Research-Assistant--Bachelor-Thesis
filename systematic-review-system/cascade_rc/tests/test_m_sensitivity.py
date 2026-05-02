from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cascade_rc.synthetic.beta_mixture import generate_paper_running_example


def _make_synthetic_parquet(
    tmp_path: Path,
    n: int = 1_000,
    seed: int = 0,
    n_calib_pos: int | None = None,
    filename: str = "TOPIC_A.parquet",
) -> Path:
    """Write a synthetic enriched parquet to tmp_path and return its path."""
    df = generate_paper_running_example(n=n, seed=seed)
    df = df.rename(columns={"y": "y_abstract"})

    if n_calib_pos is not None:
        pos_iloc = np.where(df["y_abstract"].to_numpy() == 1)[0]
        neg_iloc = np.where(df["y_abstract"].to_numpy() == 0)[0]
        is_calib = np.zeros(len(df), dtype=int)
        is_calib[pos_iloc[:n_calib_pos]] = 1
        is_calib[neg_iloc[:200]] = 1
        df["is_calib"] = is_calib
    else:
        rng = np.random.default_rng(20260429)
        is_calib = np.zeros(len(df), dtype=int)
        for label in [0, 1]:
            idx = df.index[df["y_abstract"] == label].tolist()
            calib_idx = rng.choice(idx, size=len(idx) // 2, replace=False)
            is_calib[calib_idx] = 1
        df["is_calib"] = is_calib

    path = tmp_path / filename
    df.to_parquet(path, index=False)
    return path


def test_dry_run_schema(tmp_path: Path) -> None:
    """--dry-run writes a zero-row parquet with exactly the expected schema."""
    from cascade_rc.ablations.m_sensitivity import run_sweep, PARQUET_SCHEMA

    run_sweep(data_dir=tmp_path, out_dir=tmp_path / "out", seed=42, dry_run=True)

    parquet_path = tmp_path / "out" / "m_sensitivity.parquet"
    assert parquet_path.exists(), "m_sensitivity.parquet not created"

    df = pd.read_parquet(parquet_path)
    assert len(df) == 0, f"Expected 0 rows, got {len(df)}"
    assert list(df.columns) == list(PARQUET_SCHEMA.keys()), (
        f"Column mismatch: {list(df.columns)} != {list(PARQUET_SCHEMA.keys())}"
    )
    for col, expected_dtype in PARQUET_SCHEMA.items():
        assert str(df[col].dtype) == str(expected_dtype), (
            f"Column '{col}': expected dtype '{expected_dtype}', got '{df[col].dtype}'"
        )

    skipped_path = tmp_path / "out" / "skipped_topics.json"
    assert skipped_path.exists(), "skipped_topics.json not created"
    assert json.loads(skipped_path.read_text()) == []


def test_nested_subsamples(tmp_path: Path) -> None:
    """m=26 subsample is a strict prefix of m=50 (nested-seed property).

    Both calls use the same (topic_id, global_seed) pair; m is intentionally
    excluded from the hash. permuted[:26] must be a subset of permuted[:50].
    Do NOT add m to the hash — that would break this guarantee.
    """
    from cascade_rc.ablations.m_sensitivity import _subsample_to_m

    parquet_path = _make_synthetic_parquet(tmp_path, n=5_000, seed=1)
    df = pd.read_parquet(parquet_path)

    m_plus = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())
    assert m_plus >= 50, f"Not enough cal positives for test: {m_plus}"

    df_26 = _subsample_to_m(df, 26, "TOPIC_A", global_seed=42)
    df_50 = _subsample_to_m(df, 50, "TOPIC_A", global_seed=42)

    kept_26 = set(
        df_26.index[(df_26["is_calib"] == 1) & (df_26["y_abstract"] == 1)].tolist()
    )
    kept_50 = set(
        df_50.index[(df_50["is_calib"] == 1) & (df_50["y_abstract"] == 1)].tolist()
    )

    assert len(kept_26) == 26, f"Expected 26 cal positives, got {len(kept_26)}"
    assert len(kept_50) == 50, f"Expected 50 cal positives, got {len(kept_50)}"
    assert kept_26.issubset(kept_50), (
        "m=26 kept indices must be a strict subset of m=50 kept indices. "
        "Nested-seed guarantee requires m to be excluded from the hash."
    )


def test_subsample_passthrough_when_m_gte_available(tmp_path: Path) -> None:
    """_subsample_to_m returns an unchanged copy when m >= available cal positives."""
    from cascade_rc.ablations.m_sensitivity import _subsample_to_m

    parquet_path = _make_synthetic_parquet(tmp_path, n=500, seed=2, n_calib_pos=10)
    df = pd.read_parquet(parquet_path)

    m_plus = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())
    assert m_plus == 10

    # Requesting more than available — should return full copy unchanged
    df_out = _subsample_to_m(df, m=50, topic_id="T", global_seed=0)
    cal_pos_out = int(((df_out["is_calib"] == 1) & (df_out["y_abstract"] == 1)).sum())
    assert cal_pos_out == 10, f"Expected 10 cal positives unchanged, got {cal_pos_out}"
    assert len(df_out) == len(df), "Row count must be unchanged"


def test_wss_routed_correctly() -> None:
    """_compute_wss applies auto_reject = (s < lambda_lo) to test split only.

    Setup: 3 test docs with y=[1,1,0] and s=[0.3, 0.6, 0.1].
    theta_hat = (lambda_lo=0.5, lambda_hi=1.0, tau_se=0.5).
    auto_reject = s < 0.5 → [True, False, True].
    predictions = [0, 1, 0].
    Positives captured: index 1 only (s=0.6) → recall = 1/2 = 0.5 < 0.95.
    Expected: status='recall_target_missed', achieved_recall=0.5.
    """
    from cascade_rc.ablations.m_sensitivity import _compute_wss
    from cascade_rc.certificates.store import CertificationResult

    df = pd.DataFrame({
        "is_calib": [0, 0, 0, 1, 1],
        "y_abstract": [1, 1, 0, 1, 0],
        "s":          [0.3, 0.6, 0.1, 0.9, 0.2],
        "u":          [0.5, 0.5, 0.5, 0.5, 0.5],
        "llm_y_hat":  [1, 1, 0, 1, 0],
    })

    result = CertificationResult(
        topic="T",
        status="certified",
        abstain_reason=None,
        m_plus=1,
        theta_hat=np.array([0.5, 1.0, 0.5]),
        lambda_hat_mask=np.ones(1, dtype=bool),
        theta_grid=np.array([[0.5, 1.0, 0.5]]),
        eta_lcb_grid=np.array([0.1]),
        r_hat_grid=np.array([0.1]),
        p_hb_grid=np.array([0.01]),
        alpha_dagger_grid=np.array([0.2]),
        slack_mat=np.zeros((1, 1)),
        config_snapshot={},
        timestamp="2026-05-01T00:00:00+00:00",
    )

    wss_dict = _compute_wss(result, df)
    assert wss_dict["status"] == "recall_target_missed", (
        f"Expected 'recall_target_missed', got '{wss_dict['status']}'"
    )
    assert abs(wss_dict["achieved_recall"] - 0.5) < 1e-9, (
        f"Expected achieved_recall=0.5, got {wss_dict['achieved_recall']}"
    )


def test_skip_low_prevalence_topic(tmp_path: Path) -> None:
    """Topic with m_plus_full < N_min produces zero rows and appears in skipped_topics.json.

    N_min = ceil(ln(1/0.07) / (-ln(0.9))) = 26 with default LTTBudget.
    We create a topic with only 5 calibration positives. The sweep must skip
    it entirely — no calibrate() call — and record it in skipped_topics.json.
    """
    from cascade_rc.ablations.m_sensitivity import run_sweep

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_synthetic_parquet(
        data_dir, n=1_000, seed=7, n_calib_pos=5, filename="LOW_PREV.parquet"
    )

    out_dir = tmp_path / "out"
    df = run_sweep(data_dir=data_dir, out_dir=out_dir, seed=42)

    assert len(df) == 0, f"Expected 0 rows for skipped topic, got {len(df)}"

    skipped = json.loads((out_dir / "skipped_topics.json").read_text())
    assert "LOW_PREV" in skipped, f"LOW_PREV not in skipped_topics.json: {skipped}"


def test_abstention_row_schema(tmp_path: Path) -> None:
    """Calibrate returns abstain tuple → row written with correct dtypes and NaN fields."""
    import sys
    import types
    import unittest.mock as mock

    from cascade_rc.ablations.m_sensitivity import run_sweep

    parquet_path = _make_synthetic_parquet(tmp_path, n=1_000, seed=3, n_calib_pos=50)
    out_dir = tmp_path / "out"

    # cascade_rc.calibration.main_calibrate has a transitive dependency on
    # 'confseq' which may not be installed in the test environment.  Stub it
    # out in sys.modules so that unittest.mock can import (and then patch) the
    # module without raising ModuleNotFoundError.
    _stub_modules: list[str] = []
    for mod_name in ("confseq", "confseq.betting"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            # Provide the names that wsr_lcb.py imports at module level.
            stub.betting_lower_cs = mock.MagicMock()  # type: ignore[attr-defined]
            stub.lambda_predmix_eb = mock.MagicMock()  # type: ignore[attr-defined]
            sys.modules[mod_name] = stub
            _stub_modules.append(mod_name)

    try:
        with mock.patch(
            "cascade_rc.calibration.main_calibrate.calibrate",
            return_value=(None, None, "test_abstain"),
        ), mock.patch(
            "cascade_rc.ablations.m_sensitivity._plot_topic",
        ), mock.patch(
            "cascade_rc.ablations.m_sensitivity._plot_overview",
        ):
            df = run_sweep(data_dir=tmp_path, out_dir=out_dir, seed=42)
    finally:
        # Clean up stubs so other tests are not affected.
        for mod_name in _stub_modules:
            sys.modules.pop(mod_name, None)
        # Also evict any calibration sub-modules that were loaded via the stubs.
        for key in list(sys.modules):
            if "main_calibrate" in key or "wsr_lcb" in key or "surrogate_loss" in key:
                sys.modules.pop(key, None)

    assert len(df) > 0, "expected rows when calibration abstains"
    assert df["abstention"].all(), "all rows should be abstained"
    assert (df["wss_status"] == "abstained").all()
    assert df["wss_95"].dtype == np.float64
    assert df["achieved_recall"].dtype == np.float64
    assert df["mean_eta_lcb"].dtype == np.float64
    assert df["wss_95"].isna().all()
    assert df["achieved_recall"].isna().all()
    assert df["mean_eta_lcb"].isna().all()
