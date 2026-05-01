from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cascade_rc.synthetic.beta_mixture import generate_paper_running_example


def _make_synthetic_parquet(
    tmp_path: Path,
    n: int = 1_000,
    seed: int = 0,
    n_calib_pos: int | None = None,
    filename: str = "TOPIC_A.parquet",
) -> Path:
    """Write a synthetic enriched parquet to tmp_path and return its path."""
    df = generate_paper_running_example(n=n, seed=seed)
    df = df.rename(columns={"y": "y_abstract"})

    if n_calib_pos is not None:
        pos_idx = df.index[df["y_abstract"] == 1].tolist()
        neg_idx = df.index[df["y_abstract"] == 0].tolist()
        is_calib = np.zeros(len(df), dtype=int)
        for i in pos_idx[:n_calib_pos]:
            is_calib[i] = 1
        for i in neg_idx[:200]:
            is_calib[i] = 1
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
    """--dry-run writes a zero-row parquet with exactly the expected schema."""
    from cascade_rc.ablations.m_sensitivity import run_sweep, PARQUET_SCHEMA

    run_sweep(data_dir=tmp_path, out_dir=tmp_path / "out", seed=42, dry_run=True)

    parquet_path = tmp_path / "out" / "m_sensitivity.parquet"
    assert parquet_path.exists(), "m_sensitivity.parquet not created"

    df = pd.read_parquet(parquet_path)
    assert len(df) == 0, f"Expected 0 rows, got {len(df)}"
    assert list(df.columns) == list(PARQUET_SCHEMA.keys()), (
        f"Column mismatch: {list(df.columns)} != {list(PARQUET_SCHEMA.keys())}"
    )
    for col, expected_dtype in PARQUET_SCHEMA.items():
        assert str(df[col].dtype) == str(expected_dtype), (
            f"Column '{col}': expected dtype '{expected_dtype}', got '{df[col].dtype}'"
        )

    skipped_path = tmp_path / "out" / "skipped_topics.json"
    assert skipped_path.exists(), "skipped_topics.json not created"
    assert json.loads(skipped_path.read_text()) == []
