from __future__ import annotations

import sys
import types
import unittest.mock as mock
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


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


def test_calibrate_accepts_order_fn(tmp_path: Path) -> None:
    """calibrate() must accept order_fn kwarg and complete without raising TypeError.

    Uses n_calib_pos=5 so calibrate() abstains immediately (5 < N_min=26),
    never reaching the WSR step that needs confseq.
    """
    from cascade_rc.calibration.walker import safest_to_riskiest_order
    from cascade_rc.certificates.store import CertificationResult
    from cascade_rc.config import CascadeRCConfig, LTTBudget

    # 5 positives in calib set < N_min=26 → abstention before WSR is computed
    calib_parquet = _make_synthetic_parquet(tmp_path, n=1_000, seed=0, n_calib_pos=5)
    config = CascadeRCConfig(
        ltt=LTTBudget(alpha=0.10, delta_total=0.10, delta_eta=0.03, delta_LTT=0.07, K=5),
        artefact_dir=tmp_path,
    )

    def reversed_order(grid: np.ndarray) -> np.ndarray:
        return safest_to_riskiest_order(grid)[::-1]

    _stub_modules: list[str] = []
    for mod_name in ("confseq", "confseq.betting"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            stub.betting_lower_cs = mock.MagicMock()
            stub.lambda_predmix_eb = mock.MagicMock()
            sys.modules[mod_name] = stub
            _stub_modules.append(mod_name)

    try:
        from cascade_rc.calibration.main_calibrate import calibrate

        result = calibrate("topic_rev", calib_parquet, config, order_fn=reversed_order)
        assert isinstance(result, (CertificationResult, tuple))
    except TypeError as exc:
        raise AssertionError(f"calibrate() rejected order_fn kwarg: {exc}") from exc
    finally:
        for mod_name in _stub_modules:
            sys.modules.pop(mod_name, None)
        for key in list(sys.modules):
            if any(s in key for s in ("main_calibrate", "wsr_lcb")):
                sys.modules.pop(key, None)


def test_riskiest_to_safest_is_reverse_of_default() -> None:
    """_order_riskiest_to_safest must be the exact reversal of safest_to_riskiest_order."""
    from cascade_rc.ablations.walk_ordering import DETERMINISTIC_ORDERS
    from cascade_rc.calibration.surrogate_loss import grid as sg

    g = sg(K=5)
    safe_order = DETERMINISTIC_ORDERS["safest_to_riskiest"](g)
    risky_order = DETERMINISTIC_ORDERS["riskiest_to_safest"](g)
    np.testing.assert_array_equal(safe_order, risky_order[::-1])


def test_lex_tau_se_first_sorts_by_tau_ascending() -> None:
    """lex_tau_se_first must sort by τ_SE as primary ascending key."""
    from cascade_rc.ablations.walk_ordering import DETERMINISTIC_ORDERS

    g = np.array([
        [0.1, 0.5, 0.9],
        [0.1, 0.5, 0.1],
        [0.0, 0.5, 0.5],
        [0.0, 0.5, 0.3],
    ])
    order = DETERMINISTIC_ORDERS["lex_tau_se_first"](g)
    tau_sorted = g[order, 2]
    assert list(tau_sorted) == sorted(tau_sorted.tolist()), (
        f"τ_SE must be non-decreasing after lex_tau_se_first: {tau_sorted}"
    )


def test_make_random_order_fn_is_reproducible_permutation() -> None:
    """_make_random_order_fn(seed) must return a stable full permutation."""
    from cascade_rc.ablations.walk_ordering import _make_random_order_fn
    from cascade_rc.calibration.surrogate_loss import grid as sg

    g = sg(K=5)
    G = len(g)
    fn_42 = _make_random_order_fn(42)
    order_a = fn_42(g)
    order_b = fn_42(g)

    assert len(order_a) == G
    assert set(order_a.tolist()) == set(range(G)), "must cover all G indices"
    np.testing.assert_array_equal(order_a, order_b, "same seed → identical order")

    fn_43 = _make_random_order_fn(43)
    assert not np.array_equal(fn_43(g), order_a), "different seeds must differ"


def test_dry_run_schema_walk_ordering(tmp_path: Path) -> None:
    """--dry-run produces a zero-row parquet with the exact 14-column schema."""
    from cascade_rc.ablations.walk_ordering import PARQUET_SCHEMA, run_sweep

    run_sweep(data_dir=tmp_path, out_dir=tmp_path / "out", dry_run=True)

    parquet_path = tmp_path / "out" / "walk_ordering.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert len(df) == 0
    assert list(df.columns) == list(PARQUET_SCHEMA.keys()), (
        f"Column mismatch:\n  got:  {list(df.columns)}\n  want: {list(PARQUET_SCHEMA.keys())}"
    )
    for col, expected_dtype in PARQUET_SCHEMA.items():
        assert str(df[col].dtype) == str(expected_dtype), (
            f"Column '{col}': expected '{expected_dtype}', got '{df[col].dtype}'"
        )


def test_run_sweep_abstention_row_schema(tmp_path: Path) -> None:
    """run_sweep produces (3 det + 5 random) × 1 topic = 8 abstention rows with correct schema."""
    from cascade_rc.ablations.walk_ordering import run_sweep

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
        ), mock.patch("cascade_rc.ablations.walk_ordering._plot_n_certified"), \
           mock.patch("cascade_rc.ablations.walk_ordering._plot_wss_95"):
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

    assert len(df) == 8, f"Expected 8 rows (3 det + 5 random) × 1 topic, got {len(df)}"
    assert df["abstention"].all()
    assert (df["wss_status"] == "abstained").all()
    assert (df["n_certified"] == 0).all()

    counts = df["order_name"].value_counts()
    assert counts["random"] == 5
    assert counts["safest_to_riskiest"] == 1
    assert counts["riskiest_to_safest"] == 1
    assert counts["lex_tau_se_first"] == 1

    det_rows = df[df["order_name"] != "random"]
    assert (det_rows["order_seed"] == -1).all(), "deterministic rows must use seed sentinel -1"

    rand_rows = df[df["order_name"] == "random"]
    assert set(rand_rows["order_seed"].tolist()) == {42, 43, 44, 45, 46}


def test_safest_to_riskiest_beats_riskiest_to_safest_synthetic(tmp_path: Path) -> None:
    """Lemma 6 direction check on the §3 beta-mixture toy.

    riskiest-to-safest must certify strictly fewer points than safest-to-riskiest
    because the walk fails the first hypothesis (riskiest point) and stops.
    safest-to-riskiest must certify |Λ̂| > 0.

    η̂⁻⋆ is mocked to zero everywhere (bypassing confseq/loky workers) so the
    test exercises only the walk-ordering logic in Step 8 — exactly what Lemma 6 is about.
    This does NOT validate the ≥2/3 real-data acceptance criterion (that needs CLEF-TAR data).
    """
    _stub_modules: list[str] = []
    for mod_name in ("confseq", "confseq.betting"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            stub.betting_lower_cs = mock.MagicMock()
            stub.lambda_predmix_eb = mock.MagicMock()
            sys.modules[mod_name] = stub
            _stub_modules.append(mod_name)

    try:
        from cascade_rc.ablations.walk_ordering import DETERMINISTIC_ORDERS
        from cascade_rc.calibration.main_calibrate import calibrate
        from cascade_rc.config import CascadeRCConfig, LTTBudget

        calib_parquet = _make_synthetic_parquet(tmp_path, n=5_000, seed=0)
        config = CascadeRCConfig(
            ltt=LTTBudget(alpha=0.10, delta_total=0.10, delta_eta=0.03, delta_LTT=0.07, K=5),
            artefact_dir=tmp_path,
        )

        # Return η̂⁻⋆=0 for every grid point — no confseq, no subprocesses.
        # α†(θ) = α + 0 = α, so HB p-values use the real loss/slack tensors.
        # The walk ordering in Step 8 is exercised without modification.
        def _zero_eta_lcb(slack_mat: np.ndarray, delta_eta: float, G: int,
                          topic: str, artefact_dir: object, **kw: object) -> np.ndarray:
            return np.zeros(G)

        with mock.patch(
            "cascade_rc.calibration.main_calibrate._compute_eta_lcb_chunked",
            side_effect=_zero_eta_lcb,
        ):
            result_safe = calibrate(
                "toy_safe", calib_parquet, config,
                artefact_dir=tmp_path / "safe",
                order_fn=DETERMINISTIC_ORDERS["safest_to_riskiest"],
            )
            result_risky = calibrate(
                "toy_risky", calib_parquet, config,
                artefact_dir=tmp_path / "risky",
                order_fn=DETERMINISTIC_ORDERS["riskiest_to_safest"],
            )

        safe_certified = (
            0 if isinstance(result_safe, tuple)
            else int(result_safe.lambda_hat_mask.sum())
        )
        risky_certified = (
            0 if isinstance(result_risky, tuple)
            else int(result_risky.lambda_hat_mask.sum())
        )

        assert safe_certified > 0, (
            "safest_to_riskiest certified 0 points on the §3 toy — Lemma 6 direction violated"
        )
        assert safe_certified > risky_certified, (
            f"safest_to_riskiest ({safe_certified}) must certify strictly more than "
            f"riskiest_to_safest ({risky_certified}) on the §3 toy"
        )
    finally:
        for mod_name in _stub_modules:
            sys.modules.pop(mod_name, None)
        for key in list(sys.modules):
            if any(s in key for s in ("main_calibrate", "wsr_lcb")):
                sys.modules.pop(key, None)
