"""Stratified calibration/test split for CASCADE-RC topics."""
from __future__ import annotations

from pathlib import Path

import numpy as np
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


def three_way_split(
    df: pd.DataFrame,
    score_calib_frac: float = 0.15,
    conformal_calib_frac: float = 0.50,
    seed: int = 20260429,
) -> pd.DataFrame:
    """
    Strict three-way split preserving exchangeability for Theorem 5.

    Partitions:
      is_split=0 (score_calib):    Fit Platt/Isotonic on raw RRF scores.
                                   Never used in LTT walk or test evaluation.
      is_split=1 (conformal_calib): D+ for WSR LCB on η and HB p-value walk.
                                   Scores are already transformed by the fitted
                                   calibrator — never contributed to fitting it.
      is_split=2 (test):           Held-out evaluation only.

    Stratifies on y_abstract within each partition to preserve prevalence.
    The test fraction is 1 - score_calib_frac - conformal_calib_frac.

    Args:
        df: Full topic dataframe with columns [pmid, y_abstract, s_raw, ...].
        score_calib_frac: Fraction for score calibrator training.
        conformal_calib_frac: Fraction for conformal calibration (D+).
        seed: Random seed for reproducibility.

    Returns:
        df with added column 'is_split' ∈ {0, 1, 2}.
    """
    from sklearn.model_selection import train_test_split

    test_frac = 1.0 - score_calib_frac - conformal_calib_frac
    assert test_frac > 0.0, (
        f"Splits must sum to < 1.0, got {score_calib_frac}+{conformal_calib_frac}"
    )

    rng = np.random.default_rng(seed)
    df = df.copy()
    df["is_split"] = -1  # sentinel

    idx_all = df.index.values
    y_all = df["y_abstract"].values

    # Step 1: carve out test vs (score_calib + conformal_calib)
    idx_ntest, idx_test = train_test_split(
        idx_all,
        test_size=test_frac,
        stratify=y_all,
        random_state=int(rng.integers(0, 2**31)),
    )
    df.loc[idx_test, "is_split"] = 2

    # Step 2: from non-test pool, split score_calib vs conformal_calib
    y_ntest = df.loc[idx_ntest, "y_abstract"].values
    relative_score_frac = score_calib_frac / (score_calib_frac + conformal_calib_frac)

    idx_score, idx_conf = train_test_split(
        idx_ntest,
        test_size=1.0 - relative_score_frac,
        stratify=y_ntest,
        random_state=int(rng.integers(0, 2**31)),
    )
    df.loc[idx_score, "is_split"] = 0
    df.loc[idx_conf, "is_split"] = 1

    assert (df["is_split"] == -1).sum() == 0, "All rows must be assigned a split"

    # Report split statistics
    for split_id, name in [(0, "score_calib"), (1, "conformal_calib"), (2, "test")]:
        sub = df[df.is_split == split_id]
        m_plus = sub["y_abstract"].sum()
        n_total = len(sub)
        prevalence = m_plus / n_total if n_total > 0 else 0.0
        print(
            f"  {name} (is_split={split_id}): "
            f"n={n_total}, m+={m_plus}, π={prevalence:.4f}"
        )

    return df
