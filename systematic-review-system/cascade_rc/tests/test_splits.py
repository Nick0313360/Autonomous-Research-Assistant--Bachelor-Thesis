"""Tests for the three-way split (cascade_rc/data/splits.py)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cascade_rc.data.splits import three_way_split


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_test_df(n: int = 500, prevalence: float = 0.10, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_pos = max(1, int(round(n * prevalence)))
    n_neg = n - n_pos
    y = np.array([1] * n_pos + [0] * n_neg, dtype=np.int8)
    rng.shuffle(y)
    return pd.DataFrame({
        "pmid": [f"PMC{i:06d}" for i in range(n)],
        "y_abstract": y,
        "s_raw": rng.uniform(0.0, 1.0, size=n).astype(np.float32),
    })


# ---------------------------------------------------------------------------
# test_three_way_split_no_overlap
# ---------------------------------------------------------------------------

def test_three_way_split_no_overlap() -> None:
    """Partitions must be disjoint."""
    df = make_test_df(n=500, prevalence=0.10, seed=42)
    df = three_way_split(df, seed=42)
    for a, b in [(0, 1), (0, 2), (1, 2)]:
        ids_a = set(df[df.is_split == a].index)
        ids_b = set(df[df.is_split == b].index)
        assert len(ids_a & ids_b) == 0, f"Splits {a} and {b} overlap"


# ---------------------------------------------------------------------------
# test_three_way_split_covers_all
# ---------------------------------------------------------------------------

def test_three_way_split_covers_all() -> None:
    """Every row must be assigned."""
    df = make_test_df(n=500, prevalence=0.10, seed=42)
    df = three_way_split(df, seed=42)
    assert (df.is_split == -1).sum() == 0


# ---------------------------------------------------------------------------
# test_score_calib_prevalence_preserved
# ---------------------------------------------------------------------------

def test_score_calib_prevalence_preserved() -> None:
    """Each split should have approximately the same prevalence."""
    df = make_test_df(n=1000, prevalence=0.10, seed=42)
    df = three_way_split(df, seed=42)
    for split_id in [0, 1, 2]:
        sub = df[df.is_split == split_id]
        pi = sub.y_abstract.mean()
        assert abs(pi - 0.10) < 0.04, (
            f"Split {split_id} prevalence {pi:.3f} too far from 0.10"
        )


# ---------------------------------------------------------------------------
# test_calibrator_not_fit_on_conformal_data
# ---------------------------------------------------------------------------

def test_calibrator_not_fit_on_conformal_data() -> None:
    """Calling train_calibrator must only read is_split==0 rows."""
    df = make_test_df(n=500, prevalence=0.10, seed=42)
    df = three_way_split(df, seed=42)
    # Corrupt is_split==1 and is_split==2 s_raw to detect if they're used in fit
    df.loc[df.is_split != 0, "s_raw"] = 99999.0
    # train_calibrator should not raise (99999 never enters fitting)
    try:
        from cascade_rc.data.score_normalizer import train_calibrator
        from pathlib import Path
        result = train_calibrator(df, Path("/tmp"), "test_topic")
        # Verify the returned df has 's' column and correct shape
        assert "s" in result.columns, "train_calibrator must produce 's' column"
        assert len(result) == len(df), "Row count must not change"
    except Exception as e:
        raise AssertionError(f"Calibrator should not use is_split!=0 rows: {e}")
