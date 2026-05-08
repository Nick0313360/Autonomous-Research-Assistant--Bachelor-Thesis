from __future__ import annotations

import math
import sys
import types
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cascade_rc.config import LTTBudget


@pytest.mark.parametrize("delta_eta,delta_ltt", [
    (0.01, 0.09),
    (0.03, 0.07),
    (0.05, 0.05),
    (0.07, 0.03),
    (0.09, 0.01),
])
def test_ltt_budget_ablation_pairs_are_valid(delta_eta: float, delta_ltt: float) -> None:
    """All 5 (δ_η, δ_LTT) ablation pairs must construct LTTBudget without error."""
    ltt = LTTBudget(
        alpha=0.10,
        delta_total=0.10,
        delta_eta=delta_eta,
        delta_LTT=delta_ltt,
        K=20,
    )
    assert math.isclose(ltt.delta_eta + ltt.delta_LTT, ltt.delta_total, abs_tol=1e-9)


def test_ltt_budget_validator_rejects_invalid_split() -> None:
    """Validator must raise ValueError when delta_eta + delta_LTT != delta_total."""
    with pytest.raises(ValueError, match="delta_eta"):
        LTTBudget(delta_eta=0.05, delta_LTT=0.05, delta_total=0.20)


def _make_synthetic_parquet(
    tmp_path: Path,
    n: int = 1_000,
    seed: int = 0,
    n_calib_pos: int | None = None,
    filename: str = "TOPIC_A.parquet",
) -> Path:
    from cascade_rc.synthetic.beta_mixture import generate_paper_running_example

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
    """--dry-run produces a zero-row parquet with the exact 15-column schema."""
    from cascade_rc.ablations.budget_split import PARQUET_SCHEMA, run_sweep

    run_sweep(data_dir=tmp_path, out_dir=tmp_path / "out", dry_run=True)

    parquet_path = tmp_path / "out" / "budget_split.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert len(df) == 0, f"Expected 0 rows, got {len(df)}"
    assert list(df.columns) == list(PARQUET_SCHEMA.keys()), (
        f"Column mismatch:\n  got:  {list(df.columns)}\n  want: {list(PARQUET_SCHEMA.keys())}"
    )
    for col, expected_dtype in PARQUET_SCHEMA.items():
        assert str(df[col].dtype) == str(expected_dtype), (
            f"Column '{col}': expected '{expected_dtype}', got '{df[col].dtype}'"
        )


def test_run_sweep_abstention_row_schema(tmp_path: Path) -> None:
    """When calibrate() abstains for every call, run_sweep writes correct abstention rows."""
    from cascade_rc.ablations.budget_split import run_sweep

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_synthetic_parquet(data_dir, n_calib_pos=50, filename="CD008874.parquet")

    _stub_modules: list[str] = []
    for mod_name in ("confseq", "confseq.betting"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            stub.betting_lower_cs = mock.MagicMock()
            stub.lambda_predmix_eb = mock.MagicMock()
            sys.modules[mod_name] = stub
            _stub_modules.append(mod_name)

    try:
        with mock.patch(
            "cascade_rc.calibration.main_calibrate.calibrate",
            return_value=(None, None, "abstained:m_plus=10<26"),
        ), mock.patch("cascade_rc.ablations.budget_split._plot_pareto"):
            df = run_sweep(
                data_dir=data_dir,
                out_dir=tmp_path / "out",
                topics_filter=["CD008874"],
            )
    finally:
        for mod_name in _stub_modules:
            sys.modules.pop(mod_name, None)
        for key in list(sys.modules):
            if any(s in key for s in ("main_calibrate", "wsr_lcb", "surrogate_loss")):
                sys.modules.pop(key, None)

    # 5 splits × 1 topic = 5 rows
    assert len(df) == 5, f"Expected 5 rows, got {len(df)}"
    assert df["abstention"].all()
    assert (df["wss_status"] == "abstained").all()
    assert df["wss_95"].isna().all()
    assert df["achieved_recall"].isna().all()
    assert (df["n_certified"] == 0).all()
    assert df["theta_hat_lambda_lo"].isna().all()
    assert df["alpha_dagger_at_theta"].isna().all()
    assert set(df["delta_eta"].unique()) == {0.01, 0.03, 0.05, 0.07, 0.09}
    assert set(df["delta_ltt"].unique()) == {0.09, 0.07, 0.05, 0.03, 0.01}


# ---------------------------------------------------------------------------
# test_run_topic_passes_scaled_df_to_compute_wss
# ---------------------------------------------------------------------------

def test_run_topic_passes_scaled_df_to_compute_wss(tmp_path) -> None:
    """_run_topic() with normalize_base_scores=True passes s ∈ [0,1] df to _compute_wss."""
    import numpy as np
    import pandas as pd
    from unittest.mock import patch, MagicMock
    from cascade_rc.ablations.budget_split import _run_topic
    from cascade_rc.config import CascadeRCConfig, LTTBudget

    # Build synthetic parquet with squashed s ∈ [0.011, 0.032]
    rng = np.random.default_rng(7)
    n = 300
    is_split = np.array([0] * 60 + [1] * 150 + [2] * 90, dtype=np.int8)
    y = np.zeros(n, dtype=np.int64)
    y[:12] = 1
    y[60:90] = 1
    y[210:228] = 1
    df_raw = pd.DataFrame({
        "pmid": [str(i) for i in range(n)],
        "s": rng.uniform(0.011, 0.032, n),
        "u": rng.uniform(0.0, 1.0, n),
        "y_abstract": y,
        "llm_y_hat": rng.integers(0, 2, n, dtype=np.int64),
        "is_split": is_split,
        "is_calib": np.where(np.array([0] * 60 + [1] * 150 + [2] * 90) == 1, 1, 0),
    })
    parquet_path = tmp_path / "CD_test.parquet"
    df_raw.to_parquet(parquet_path, index=False)

    # Build a fake CertificationResult with theta_hat in [0,1] scaled space
    mock_result = MagicMock()
    mock_result.theta_hat = np.array([0.3, 0.7, 0.5])
    mock_result.lambda_hat_mask = np.array([True, False])
    mock_result.theta_grid = np.array([[0.3, 0.7, 0.5], [0.0, 0.0, 0.0]])
    mock_result.slack_mat = np.zeros((2, 30))
    mock_result.eta_lcb_grid = np.zeros(2)
    mock_result.alpha_dagger_grid = np.zeros(2)
    mock_result.m_plus = 30

    captured = {}

    def fake_compute_wss(result, df_full):
        captured["df"] = df_full
        return {"wss": 0.5, "status": "ok", "achieved_recall": 0.95}

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

    with patch("cascade_rc.calibration.main_calibrate.calibrate", return_value=mock_result):
        with patch("cascade_rc.ablations.budget_split._compute_wss", side_effect=fake_compute_wss):
            _run_topic(
                topic_id="CD_test",
                parquet_path=parquet_path,
                delta_eta=0.03,
                delta_ltt=0.07,
                config=cfg,
                out_dir=tmp_path,
            )

    assert "df" in captured, "_compute_wss was never called"
    s_max = float(captured["df"]["s"].max())
    s_min = float(captured["df"]["s"].min())
    assert s_max == pytest.approx(1.0, abs=1e-9), (
        f"Expected s.max()=1.0 after scaling, got {s_max}"
    )
    assert s_min == pytest.approx(0.0, abs=1e-9), (
        f"Expected s.min()=0.0 after scaling, got {s_min}"
    )
