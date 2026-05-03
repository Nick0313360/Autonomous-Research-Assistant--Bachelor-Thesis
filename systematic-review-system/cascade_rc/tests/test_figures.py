"""Tests for cascade_rc.evaluation.figures."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from cascade_rc.evaluation.figures import (
    _apply_ieee_style,
    _load_fig1_data,
    _load_fig2_data,
    _load_fig3_data,
    _synthetic_figure1_data,
    _synthetic_figure2_data,
    _synthetic_figure3_data,
    ALPHAS,
    METHODS,
)


def test_ieee_style_sets_font_size() -> None:
    _apply_ieee_style()
    assert plt.rcParams["font.size"] == 8


def test_ieee_style_sets_serif() -> None:
    _apply_ieee_style()
    assert plt.rcParams["font.family"] == ["serif"]


def test_constants_coverage() -> None:
    assert len(ALPHAS) == 6
    assert "CASCADE-RC" in METHODS
    assert len(METHODS) == 5


def test_synthetic_fig1_has_all_methods() -> None:
    rng = np.random.default_rng(0)
    df = _synthetic_figure1_data(rng)
    assert set(df["method"].unique()) == set(METHODS)


def test_synthetic_fig1_cascade_rc_below_diagonal() -> None:
    rng = np.random.default_rng(0)
    df = _synthetic_figure1_data(rng)
    crc = df[df["method"] == "CASCADE-RC"]
    assert (crc["fnr"].values <= crc["alpha"].values + 1e-9).all(), \
        "CASCADE-RC FNR must not exceed alpha (validity guarantee)"


def test_synthetic_fig2_has_all_methods() -> None:
    rng = np.random.default_rng(0)
    df = _synthetic_figure2_data(rng)
    assert set(df["method"].unique()) == set(METHODS)


def test_synthetic_fig3_fractions_sum_to_one() -> None:
    rng = np.random.default_rng(0)
    df = _synthetic_figure3_data(rng)
    totals = df[["cheap_reject", "auto_include", "llm", "human"]].sum(axis=1)
    np.testing.assert_allclose(totals.values, 1.0, atol=1e-9)


def test_loaders_fall_back_to_synthetic_when_no_parquets(tmp_path: Path) -> None:
    df1 = _load_fig1_data(tmp_path)
    assert set(df1["method"].unique()) == set(METHODS)

    df2 = _load_fig2_data(tmp_path)
    assert set(df2["method"].unique()) == set(METHODS)

    df3 = _load_fig3_data(tmp_path)
    assert set(df3["alpha"].unique()) == set(ALPHAS)


def test_loaders_use_real_autostop_parquet(tmp_path: Path) -> None:
    baseline_dir = tmp_path / "baselines"
    baseline_dir.mkdir()
    rows = [
        {"method": "autostop", "topic_id": "CD008874",
         "target_recall": 0.95, "examined": 100,
         "recall_achieved": 0.97, "wss_95": 0.42,
         "wss_status": "ok", "peak_rss_kb": float("nan")}
    ]
    pd.DataFrame(rows).to_parquet(baseline_dir / "autostop_results.parquet", index=False)
    df = _load_fig1_data(tmp_path)
    autostop_rows = df[df["method"] == "AUTOSTOP"]
    assert len(autostop_rows) >= 1
    assert float(autostop_rows.iloc[0]["alpha"]) == pytest.approx(0.05)


from cascade_rc.evaluation.figures import plot_figure1, plot_figure2, plot_figure3


def test_plot_figure1_creates_pdf_and_png(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    df = _synthetic_figure1_data(rng)
    plot_figure1(df, tmp_path)
    assert (tmp_path / "figure1_risk_validity.pdf").exists()
    assert (tmp_path / "figure1_risk_validity.png").exists()


def test_plot_figure2_creates_pdf_and_png(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    df = _synthetic_figure2_data(rng)
    plot_figure2(df, tmp_path)
    assert (tmp_path / "figure2_wss_efficiency.pdf").exists()
    assert (tmp_path / "figure2_wss_efficiency.png").exists()


def test_plot_figure3_creates_pdf_and_png(tmp_path: Path) -> None:
    rng = np.random.default_rng(0)
    df = _synthetic_figure3_data(rng)
    plot_figure3(df, tmp_path)
    assert (tmp_path / "figure3_escalation.pdf").exists()
    assert (tmp_path / "figure3_escalation.png").exists()
