"""Tests for cascade_rc.baselines.run_autostop."""
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
_Y = [1] * 20 + [0] * 180   # 20 relevant


def _make_topic_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "pmid":       _PMIDS,
        "title":      ["t"] * _N,
        "abstract":   ["a"] * _N,
        "y_abstract": _Y,
    }).to_parquet(path, index=False)


def _fake_autostop(topic_id: str, examined_count: int = 50) -> None:
    """Side-effect for mock: write fake CSV and run file to current RET_DIR.

    Must read RET_DIR from the driver's module object (imported via sys.path),
    not from the package path — they are separate module objects in sys.modules.
    """
    import cascade_rc.baselines.run_autostop as _driver

    ret_dir = Path(_driver._as_utils.RET_DIR)

    csv_dir = ret_dir / "crc" / "interaction" / "fake" / "test" / "0"
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_content = f"1,10,{_N},{examined_count},20,20,0.1,0.1,0.9,0.3,0.95,0.9\n"
    (csv_dir / f"{topic_id}.csv").write_text(csv_content)

    run_dir = ret_dir / "crc" / "tar_run" / "fake" / "test" / "0"
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"{topic_id}\tAF\t{pmid}\t{i+1}\t{-i}\tmrun"
             for i, pmid in enumerate(_PMIDS[:examined_count])]
    (run_dir / f"{topic_id}.run").write_text("\n".join(lines))


def test_dry_run_zero_rows_correct_schema(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_autostop import run_sweep

    df = run_sweep(
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        dry_run=True,
    )
    assert len(df) == 0
    for col, dtype in _SCHEMA.items():
        assert col in df.columns, f"Missing column: {col}"
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"


def test_dry_run_parquet_written(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_autostop import run_sweep

    out_dir = tmp_path / "out"
    run_sweep(data_dir=tmp_path / "data", out_dir=out_dir, dry_run=True)
    assert (out_dir / "autostop_results.parquet").exists()


def test_no_parquets_raises(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_autostop import run_sweep

    with pytest.raises(FileNotFoundError):
        run_sweep(data_dir=tmp_path / "empty", out_dir=tmp_path / "out")


def test_single_topic_single_recall_mock(tmp_path: Path) -> None:
    """Functional test: mocked autostop_method writes expected files; driver parses them."""
    from cascade_rc.baselines.run_autostop import run_sweep

    data_dir = tmp_path / "data"
    _make_topic_parquet(data_dir / "CD008874.parquet")

    def _side_effect(*args, **kwargs) -> None:
        _fake_autostop("CD008874", examined_count=50)

    with mock.patch("cascade_rc.baselines.run_autostop._autostop_method",
                    side_effect=_side_effect):
        df = run_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "out",
            topics=["CD008874"],
            recalls=[0.95],
        )

    assert len(df) == 1
    row = df.iloc[0]
    assert row["method"] == "autostop"
    assert row["topic_id"] == "CD008874"
    assert float(row["target_recall"]) == pytest.approx(0.95)
    assert int(row["examined"]) == 50
    assert row["wss_status"] in {"ok", "recall_target_missed", "no_relevant_docs"}
    assert int(row["peak_rss_kb"]) > 0


def test_output_schema_dtypes_after_real_run(tmp_path: Path) -> None:
    """Verify astype(_OUTPUT_SCHEMA) produces correct column dtypes."""
    from cascade_rc.baselines.run_autostop import run_sweep

    data_dir = tmp_path / "data"
    _make_topic_parquet(data_dir / "CD008874.parquet")

    def _side_effect(*args, **kwargs) -> None:
        _fake_autostop("CD008874", examined_count=50)

    with mock.patch("cascade_rc.baselines.run_autostop._autostop_method",
                    side_effect=_side_effect):
        df = run_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "out",
            topics=["CD008874"],
            recalls=[0.95],
        )

    for col, dtype in _SCHEMA.items():
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"


def test_schema_parity_concat(tmp_path: Path) -> None:
    """pd.concat of autostop_df and rlstop_df must yield 8 rows, no NaN method column."""
    from cascade_rc.baselines.run_autostop import run_sweep as as_sweep
    from cascade_rc.baselines.run_rlstop import run_sweep as rl_sweep

    data_dir = tmp_path / "data"
    _make_topic_parquet(data_dir / "CD008874.parquet")

    def _as_side_effect(*args, **kwargs) -> None:
        _fake_autostop("CD008874", examined_count=50)

    mock_model = mock.MagicMock()
    mock_model.predict.return_value = (np.array(1), None)

    with mock.patch("cascade_rc.baselines.run_autostop._autostop_method",
                    side_effect=_as_side_effect):
        df_as = as_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "as_out",
            topics=["CD008874"],
            recalls=[0.80, 0.90, 0.95, 1.0],
        )

    with (
        mock.patch("cascade_rc.baselines.run_rlstop._train_model", return_value=mock_model),
        mock.patch("cascade_rc.baselines.run_rlstop._build_training_dicts", return_value=({}, {})),
    ):
        df_rl = rl_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "rl_out",
            train_dir=tmp_path / "train",
            topics=["CD008874"],
            recalls=[0.80, 0.90, 0.95, 1.0],
        )

    combined = pd.concat([df_as, df_rl], ignore_index=True)

    assert len(combined) == 8   # 1 topic × 4 recalls × 2 methods
    assert combined["method"].notna().all()
    assert set(combined["method"].unique()) == {"autostop", "rlstop"}
    assert list(combined.columns) == list(_SCHEMA.keys())
