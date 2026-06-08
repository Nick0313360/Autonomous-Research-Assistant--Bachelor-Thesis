"""Tests for cascade_rc.baselines.run_rlstop."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

_SCHEMA = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "int64",
}

_N = 200
_PMIDS = [str(i) for i in range(_N)]
_Y = [1] * 20 + [0] * 180


def _make_topic_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "pmid":       _PMIDS,
        "title":      ["A B C"] * _N,
        "abstract":   ["D E F"] * _N,
        "y_abstract": _Y,
    }).to_parquet(path, index=False)


def test_dry_run_zero_rows_correct_schema(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_rlstop import run_sweep

    df = run_sweep(
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        train_dir=tmp_path / "train",
        dry_run=True,
    )
    assert len(df) == 0
    for col, dtype in _SCHEMA.items():
        assert col in df.columns, f"Missing column: {col}"
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"


def test_dry_run_parquet_written(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_rlstop import run_sweep

    out_dir = tmp_path / "out"
    run_sweep(
        data_dir=tmp_path / "data",
        out_dir=out_dir,
        train_dir=tmp_path / "train",
        dry_run=True,
    )
    assert (out_dir / "rlstop_results.parquet").exists()


def test_no_parquets_raises(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_rlstop import run_sweep

    with pytest.raises(FileNotFoundError):
        run_sweep(
            data_dir=tmp_path / "empty",
            out_dir=tmp_path / "out",
            train_dir=tmp_path / "train",
        )


def test_infer_one_with_mock_model(tmp_path: Path) -> None:
    """Mock model.predict to return STOP(1) immediately; verify row schema."""
    from cascade_rc.baselines.run_rlstop import _infer_one, _inject_globals

    data_dir = tmp_path / "data"
    df_topic = pd.DataFrame({
        "pmid":       _PMIDS,
        "title":      ["term"] * _N,
        "abstract":   ["word"] * _N,
        "y_abstract": _Y,
    })

    infer_doc = {"CD008874": _PMIDS[:]}
    infer_rel = {"CD008874": list(_Y)}
    _inject_globals("CD008874", infer_doc, infer_rel)

    mock_model = mock.MagicMock()
    mock_model.predict.return_value = (np.array(1), None)

    row = _infer_one("CD008874", df_topic, 0.95, mock_model, data_dir)

    assert row["method"] == "rlstop"
    assert row["topic_id"] == "CD008874"
    assert float(row["target_recall"]) == pytest.approx(0.95)
    assert row["wss_status"] in {"ok", "recall_target_missed", "no_relevant_docs"}
    assert int(row["peak_rss_kb"]) > 0


def test_make_windows_basic() -> None:
    from cascade_rc.baselines.run_rlstop import _make_windows

    windows = _make_windows(vector_size=100, n_docs=200)
    assert len(windows) == 100
    assert windows[0] == (0, 2)
    assert windows[99] == (198, 200)


def test_make_windows_small_docs() -> None:
    from cascade_rc.baselines.run_rlstop import _make_windows

    windows = _make_windows(vector_size=100, n_docs=119)
    assert len(windows) == 100
    assert windows[0] == (0, 1)


def test_output_schema_dtypes_after_mock_infer(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_rlstop import run_sweep

    data_dir = tmp_path / "data"
    _make_topic_parquet(data_dir / "CD008874.parquet")

    mock_model = mock.MagicMock()
    mock_model.predict.return_value = (np.array(1), None)

    with (
        mock.patch("cascade_rc.baselines.run_rlstop._train_model", return_value=mock_model),
        mock.patch("cascade_rc.baselines.run_rlstop._build_training_dicts", return_value=({}, {})),
    ):
        df = run_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "out",
            train_dir=tmp_path / "train",
            topics=["CD008874"],
            recalls=[0.95],
        )

    assert len(df) == 1
    for col, dtype in _SCHEMA.items():
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"
