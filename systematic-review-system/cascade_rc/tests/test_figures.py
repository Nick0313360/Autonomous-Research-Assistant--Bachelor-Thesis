"""Tests for cascade_rc.evaluation.figures."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest

from cascade_rc.evaluation.figures import _apply_ieee_style, ALPHAS, METHODS


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
