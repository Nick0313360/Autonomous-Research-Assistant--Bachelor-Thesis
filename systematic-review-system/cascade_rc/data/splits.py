"""Stratified calibration/test split for CASCADE-RC topics."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def stratified_calib_test_split(
    df: pd.DataFrame,
    calib_frac: float,
    fallback_8020_when_m_plus_at_least: int,
    seed: int,
    out_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (calib_df, test_df) stratified on y_abstract.

    If df.y_abstract.sum() >= fallback_8020_when_m_plus_at_least the split
    uses calib_frac=0.8 regardless of the supplied value.

    When out_path is given the combined frame (all rows, is_calib ∈ {0,1}) is
    written as a parquet file for deterministic re-use across runs.
    """
    from sklearn.model_selection import train_test_split  # local import keeps module light

    m_plus = int(df["y_abstract"].sum())
    actual_frac = 0.8 if m_plus >= fallback_8020_when_m_plus_at_least else calib_frac

    calib_df, test_df = train_test_split(
        df,
        train_size=actual_frac,
        stratify=df["y_abstract"],
        random_state=seed,
    )

    calib_df = calib_df.copy()
    test_df = test_df.copy()
    calib_df["is_calib"] = pd.array([1] * len(calib_df), dtype="int8")
    test_df["is_calib"] = pd.array([0] * len(test_df), dtype="int8")

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        combined = (
            pd.concat([calib_df, test_df], ignore_index=True)
            .sort_values("pmid")
            .reset_index(drop=True)
        )
        combined.to_parquet(out_path, index=False)

    return calib_df.reset_index(drop=True), test_df.reset_index(drop=True)
