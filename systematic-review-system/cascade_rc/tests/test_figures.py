"""Tests for cascade_rc.evaluation.figures."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest

from cascade_rc.evaluation.figures import (
    _apply_ieee_style,
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
