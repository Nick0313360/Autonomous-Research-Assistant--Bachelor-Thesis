"""cascade_rc/tests/test_score_normalizer.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_calibrators(
    seed: int = 0,
) -> tuple[IsotonicRegression, LogisticRegression, np.ndarray, np.ndarray]:
    """Return (iso, platt) fitted on synthetic RRF-range data."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.016, 0.033, 200)
    y = (x + rng.uniform(0.0, 0.004, 200) > np.median(x)).astype(int)
    iso = IsotonicRegression(out_of_bounds="clip").fit(x, y)
    platt = LogisticRegression(
        C=1e10, solver="lbfgs", max_iter=1000, random_state=42
    ).fit(x.reshape(-1, 1), y)
    return iso, platt, x, y


# ---------------------------------------------------------------------------
# test_calibrator_monotone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chosen", ["isotonic", "platt"])
def test_calibrator_monotone(chosen: str) -> None:
    """Both calibrators produce non-decreasing predictions on a sorted grid."""
    from cascade_rc.data.score_normalizer import CalibratorBundle

    iso, platt, _, _ = _make_calibrators(seed=0)
    bundle = CalibratorBundle(
        {"chosen": chosen, "isotonic": iso, "platt": platt, "metadata": {}}
    )
    grid = np.linspace(0.016, 0.033, 200)
    preds = bundle.predict(grid)
    diffs = np.diff(preds)
    assert np.all(diffs >= -1e-10), (
        f"{chosen}: not monotone; min diff = {diffs.min():.2e}"
    )


# ---------------------------------------------------------------------------
# test_calibrator_brier_lower_than_uncalibrated
# ---------------------------------------------------------------------------

def test_calibrator_brier_lower_than_uncalibrated() -> None:
    """Chosen calibrator Brier score beats the identity map on the val set."""
    from cascade_rc.data.score_normalizer import CalibratorBundle

    rng = np.random.default_rng(42)
    x = rng.uniform(0.016, 0.033, 300)
    y = (x + rng.uniform(0.0, 0.004, 300) > np.median(x)).astype(int)

    n_train = 240
    x_train, y_train = x[:n_train], y[:n_train]
    x_val, y_val = x[n_train:], y[n_train:]

    iso = IsotonicRegression(out_of_bounds="clip").fit(x_train, y_train)
    platt = LogisticRegression(
        C=1e10, solver="lbfgs", max_iter=1000, random_state=42
    ).fit(x_train.reshape(-1, 1), y_train)

    p_iso = iso.predict(x_val)
    p_platt = platt.predict_proba(x_val.reshape(-1, 1))[:, 1]
    chosen = "isotonic" if log_loss(y_val, p_iso) <= log_loss(y_val, p_platt) else "platt"

    bundle = CalibratorBundle(
        {"chosen": chosen, "isotonic": iso, "platt": platt, "metadata": {}}
    )
    p_cal = bundle.predict(x_val)
    p_raw = np.clip(x_val, 0.0, 1.0)  # identity map: RRF scores ≈ 0.016–0.033

    assert brier_score_loss(y_val, p_cal) < brier_score_loss(y_val, p_raw), (
        f"Calibrator Brier {brier_score_loss(y_val, p_cal):.4f} >= "
        f"identity Brier {brier_score_loss(y_val, p_raw):.4f}"
    )


# ---------------------------------------------------------------------------
# test_persisted_pkl_roundtrip
# ---------------------------------------------------------------------------

def test_persisted_pkl_roundtrip(tmp_path: Path) -> None:
    """Predictions from a loaded .pkl match in-memory predictions exactly."""
    from cascade_rc.data.score_normalizer import (
        CalibratorBundle,
        load_calibrator,
        save_calibrator,
    )

    iso, platt, _, _ = _make_calibrators(seed=7)
    bundle_dict = {
        "chosen": "isotonic",
        "isotonic": iso,
        "platt": platt,
        "metadata": {"nll_isotonic": 0.5, "nll_platt": 0.6},
    }
    pkl_path = tmp_path / "test.pkl"
    save_calibrator(bundle_dict, pkl_path)
    loaded = load_calibrator(pkl_path)

    grid = np.linspace(0.016, 0.033, 50)
    in_memory = CalibratorBundle(bundle_dict).predict(grid)
    from_disk = loaded.predict(grid)

    assert np.allclose(in_memory, from_disk), "Predictions differ after pkl roundtrip"


# ---------------------------------------------------------------------------
# test_calibrator_predict_empty_input
# ---------------------------------------------------------------------------

def test_calibrator_predict_empty_input() -> None:
    """predict(np.array([])) returns a zero-length array without raising."""
    from cascade_rc.data.score_normalizer import CalibratorBundle

    iso, platt, _, _ = _make_calibrators(seed=1)
    bundle = CalibratorBundle(
        {"chosen": "isotonic", "isotonic": iso, "platt": platt, "metadata": {}}
    )
    result = bundle.predict(np.array([]))
    assert isinstance(result, np.ndarray), f"Expected np.ndarray, got {type(result)}"
    assert result.shape == (0,), f"Expected shape (0,), got {result.shape}"
    assert result.dtype == np.float64, f"Expected float64, got {result.dtype}"


# ---------------------------------------------------------------------------
# test_minmax_scale_s
# ---------------------------------------------------------------------------

import pandas as pd


def test_minmax_scale_s_squashed_range() -> None:
    """Squashed range [0.011, 0.032] is mapped to [0.0, 1.0]."""
    from cascade_rc.data.score_normalizer import minmax_scale_s

    rng = np.random.default_rng(0)
    s_raw = rng.uniform(0.011, 0.032, 200)
    df = pd.DataFrame({"s": s_raw, "y_abstract": rng.integers(0, 2, 200)})
    df_scaled = minmax_scale_s(df)

    assert df_scaled is not df, "Must return a copy, not mutate in-place"
    assert float(df_scaled["s"].min()) == pytest.approx(0.0, abs=1e-12)
    assert float(df_scaled["s"].max()) == pytest.approx(1.0, abs=1e-12)
    # rank preservation: Spearman = 1.0
    from scipy.stats import spearmanr
    rho, _ = spearmanr(df["s"].values, df_scaled["s"].values)
    assert rho == pytest.approx(1.0, abs=1e-10)


def test_minmax_scale_s_idempotent() -> None:
    """Scaling twice is idempotent (second scaling of [0,1] is a no-op)."""
    from cascade_rc.data.score_normalizer import minmax_scale_s

    rng = np.random.default_rng(1)
    s_raw = rng.uniform(0.011, 0.032, 100)
    df = pd.DataFrame({"s": s_raw})
    df_once = minmax_scale_s(df)
    df_twice = minmax_scale_s(df_once)
    # Second scaling of already-[0,1] data should be a no-op
    np.testing.assert_allclose(df_twice["s"].values, df_once["s"].values, atol=1e-12)


def test_minmax_scale_s_constant_noop() -> None:
    """Constant s column (s_min == s_max) returns the dataframe unchanged."""
    from cascade_rc.data.score_normalizer import minmax_scale_s

    df = pd.DataFrame({"s": [0.02] * 50})
    df_out = minmax_scale_s(df)
    # must not raise, must not produce NaN
    assert not df_out["s"].isna().any()
    np.testing.assert_array_equal(df_out["s"].values, df["s"].values)
