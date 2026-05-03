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
    """--dry-run produces a zero-row parquet with the exact 14-column schema."""
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
