"""Tests for cascade_rc.evaluation.figures."""
from __future__ import annotations

import hashlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from cascade_rc.evaluation.figures import (
    _apply_ieee_style,
    gen_figures,
    load_autostop_wss_reference,
    main,
    plot_budget_split_ablation,
    plot_operational_cost,
    plot_risk_validity,
)


def test_ieee_style_sets_font_size() -> None:
    _apply_ieee_style()
    assert plt.rcParams["font.size"] == 8


def test_ieee_style_sets_serif() -> None:
    _apply_ieee_style()
    assert plt.rcParams["font.family"] == ["serif"]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _minimal_alpha_sweep() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for topic_id in ("CD008874", "CD012080"):
        for alpha in (0.01, 0.10, 0.20):
            rows.append(
                {
                    "topic_id": topic_id,
                    "alpha": alpha,
                    "status": "certified",
                    "fnr_test": float(alpha) * 0.5,
                    "wss_95": 0.4,
                    "frac_human_review": 0.3,
                    "scrc_t_fnr": float(alpha) + 0.05,
                    "scrc_i_fnr": float(alpha) + 0.04,
                    "autostop_fnr": float(alpha) + 0.06,
                    "uncalibrated_fnr": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _minimal_budget_split() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for topic_id in ("CD008874", "CD012080"):
        for de in (0.01, 0.03, 0.07):
            rows.append(
                {
                    "topic_id": topic_id,
                    "delta_eta": de,
                    "n_certified": 5,
                    "slack_ratio": 0.9,
                }
            )
    return pd.DataFrame(rows)


def test_plot_risk_validity_creates_outputs(tmp_path: Path) -> None:
    plot_risk_validity(_minimal_alpha_sweep(), tmp_path)
    assert (tmp_path / "fig1_risk_validity.pdf").exists()
    assert (tmp_path / "fig1_risk_validity.png").exists()


def test_plot_operational_cost_creates_outputs(tmp_path: Path) -> None:
    plot_operational_cost(_minimal_alpha_sweep(), 0.42, tmp_path)
    assert (tmp_path / "fig2_operational_cost.pdf").exists()
    assert (tmp_path / "fig2_operational_cost.png").exists()


def test_plot_budget_split_ablation_creates_outputs(tmp_path: Path) -> None:
    plot_budget_split_ablation(_minimal_budget_split(), tmp_path)
    assert (tmp_path / "fig3_budget_split_ablation.pdf").exists()
    assert (tmp_path / "fig3_budget_split_ablation.png").exists()


def test_gen_figures_with_parquets(tmp_path: Path) -> None:
    res = tmp_path / "results"
    res.mkdir(parents=True)
    abl = tmp_path / "ablations"
    abl.mkdir(parents=True)
    auto = tmp_path / "baselines" / "autostop"
    auto.mkdir(parents=True)

    _minimal_alpha_sweep().to_parquet(res / "alpha_sweep.parquet", index=False)
    _minimal_budget_split().to_parquet(abl / "budget_split.parquet", index=False)
    pd.DataFrame(
        [
            {
                "method": "autostop",
                "topic_id": "CD008874",
                "target_recall": 0.95,
                "examined": 100,
                "recall_achieved": 0.96,
                "wss_95": 0.41,
                "wss_status": "ok",
                "peak_rss_kb": 0,
            }
        ]
    ).to_parquet(auto / "autostop_results.parquet", index=False)

    gen_figures(artefact_dir=tmp_path)
    fig_dir = tmp_path / "figures"
    for stem in (
        "fig1_risk_validity",
        "fig2_operational_cost",
        "fig3_budget_split_ablation",
    ):
        assert (fig_dir / f"{stem}.pdf").exists(), f"{stem}.pdf missing"
        assert (fig_dir / f"{stem}.png").exists(), f"{stem}.png missing"


def test_main_alias_calls_gen_figures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Path | None] = {"path": None}

    def _stub(path: Path) -> None:
        called["path"] = path

    monkeypatch.setattr("cascade_rc.evaluation.figures.gen_figures", _stub)
    main(artefact_dir=tmp_path)
    assert called["path"] == tmp_path


def test_gen_figures_is_png_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    for name in ("run1", "run2"):
        root = tmp_path / name
        res = root / "results"
        res.mkdir(parents=True)
        abl = root / "ablations"
        abl.mkdir(parents=True)
        auto = root / "baselines" / "autostop"
        auto.mkdir(parents=True)
        _minimal_alpha_sweep().to_parquet(res / "alpha_sweep.parquet", index=False)
        _minimal_budget_split().to_parquet(abl / "budget_split.parquet", index=False)
        pd.DataFrame(
            [
                {
                    "method": "autostop",
                    "topic_id": "CD008874",
                    "target_recall": 0.95,
                    "wss_95": 0.42,
                }
            ]
        ).to_parquet(auto / "autostop_results.parquet", index=False)
        gen_figures(artefact_dir=root)

    for stem in (
        "fig1_risk_validity",
        "fig2_operational_cost",
        "fig3_budget_split_ablation",
    ):
        p1 = tmp_path / "run1" / "figures" / f"{stem}.png"
        p2 = tmp_path / "run2" / "figures" / f"{stem}.png"
        assert _md5(p1) == _md5(p2), f"{stem}.png not deterministic"


def test_load_autostop_wss_reference(tmp_path: Path) -> None:
    auto = tmp_path / "baselines" / "autostop"
    auto.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "method": "autostop",
                "topic_id": "A",
                "target_recall": 0.95,
                "wss_95": 0.5,
            },
            {
                "method": "autostop",
                "topic_id": "B",
                "target_recall": 0.95,
                "wss_95": 0.7,
            },
        ]
    ).to_parquet(auto / "autostop_results.parquet", index=False)
    assert load_autostop_wss_reference(tmp_path) == pytest.approx(0.6)
