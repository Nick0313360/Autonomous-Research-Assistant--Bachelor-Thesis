"""
tests/test_score_normalizer.py
================================
TDD: written *before* the implementation in cascade_rc/data/score_normalizer.py.

Three required behaviours
-------------------------
1. All s_score values produced by apply_platt are in [0, 1].
2. Spearman correlation between s_score and y_abstract is positive when
   raw_score is informative.
3. The Platt calibrator's predictions are monotone (non-decreasing) in
   raw_score (sanity check for logistic sigmoid).

Two structural tests
--------------------
4. fit_platt returns a fitted sklearn LogisticRegression (PlattCalibrator).
5. compute_raw_scores returns a DataFrame with all required columns.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Synthetic-data factory
# ---------------------------------------------------------------------------

def _make_synthetic(n: int = 200, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (raw_scores, y) where raw_scores have a genuine positive
    Spearman correlation with y (binary).  Values are in the realistic
    RRF-score range (~0.016 – 0.033 for typical corpora).
    """
    rng = np.random.default_rng(seed)
    raw_scores = rng.uniform(0.016, 0.033, n)
    # Use a noisy threshold so the signal is real but imperfect
    y = (raw_scores + rng.uniform(0.0, 0.004, n) > np.median(raw_scores)).astype(int)
    return raw_scores, y


# ---------------------------------------------------------------------------
# 1. s_score ∈ [0, 1]
# ---------------------------------------------------------------------------

def test_apply_platt_values_in_unit_interval() -> None:
    """All s_score outputs of apply_platt must lie in [0, 1]."""
    from cascade_rc.data.score_normalizer import apply_platt, fit_platt

    raw_scores, y = _make_synthetic(200, seed=42)
    calibrator = fit_platt(raw_scores, y)
    s = apply_platt(calibrator, raw_scores)

    assert s.shape == raw_scores.shape, "Output shape mismatch"
    assert np.all(s >= 0.0), f"Min s_score {s.min():.6f} < 0"
    assert np.all(s <= 1.0), f"Max s_score {s.max():.6f} > 1"


# ---------------------------------------------------------------------------
# 2. Spearman(s_score, y) > 0
# ---------------------------------------------------------------------------

def test_spearman_correlation_positive() -> None:
    """Spearman(s_score, y_abstract) must be > 0 with informative raw scores."""
    from scipy.stats import spearmanr
    from cascade_rc.data.score_normalizer import apply_platt, fit_platt

    raw_scores, y = _make_synthetic(400, seed=7)
    calibrator = fit_platt(raw_scores, y)
    s = apply_platt(calibrator, raw_scores)
    corr, _ = spearmanr(s, y)

    assert corr > 0, f"Expected positive Spearman correlation, got {corr:.4f}"


# ---------------------------------------------------------------------------
# 3. Monotonicity of Platt predictions
# ---------------------------------------------------------------------------

def test_platt_predictions_monotone_in_raw_score() -> None:
    """
    For a sorted input, apply_platt must return a non-decreasing sequence
    (logistic sigmoid is strictly monotone, so tiny fp noise is the only risk).
    """
    from cascade_rc.data.score_normalizer import apply_platt, fit_platt

    raw_scores, y = _make_synthetic(200, seed=1)
    calibrator = fit_platt(raw_scores, y)

    sorted_scores = np.sort(raw_scores)
    s = apply_platt(calibrator, sorted_scores)
    violations = np.diff(s)

    assert np.all(violations >= -1e-10), (
        f"Platt predictions not monotone; "
        f"first violation: {violations[violations < -1e-10][0]:.2e}"
    )


# ---------------------------------------------------------------------------
# 4. fit_platt returns a fitted LogisticRegression
# ---------------------------------------------------------------------------

def test_fit_platt_returns_logistic_regression() -> None:
    """fit_platt must return a fitted sklearn LogisticRegression."""
    from sklearn.linear_model import LogisticRegression
    from cascade_rc.data.score_normalizer import fit_platt

    raw_scores, y = _make_synthetic(100, seed=99)
    calibrator = fit_platt(raw_scores, y)

    assert isinstance(calibrator, LogisticRegression), (
        f"Expected LogisticRegression, got {type(calibrator)}"
    )
    assert hasattr(calibrator, "coef_"), "Calibrator was not fitted (missing coef_)"


# ---------------------------------------------------------------------------
# 5. compute_raw_scores — column contract (mocked infrastructure)
# ---------------------------------------------------------------------------

def test_compute_raw_scores_returns_required_columns(tmp_path: Path) -> None:
    """
    compute_raw_scores must return a DataFrame containing
    {pmid, bm25, specter2_cos, raw_score, y_abstract}.

    The SharedEncoderService and HybridRetriever are mocked to avoid loading
    the SPECTER2 model during CI.
    """
    from cascade_rc.data.score_normalizer import compute_raw_scores

    n = 10
    df = pd.DataFrame(
        {
            "pmid": [str(i) for i in range(n)],
            "title": [f"Title {i}" for i in range(n)],
            "abstract": [f"Abstract {i}" for i in range(n)],
            "y_abstract": ([1, 0] * (n // 2)),
        }
    )
    df["y_abstract"] = df["y_abstract"].astype("int8")
    parquet_path = tmp_path / "CD008874.parquet"
    df.to_parquet(parquet_path, index=False)

    with (
        patch("cascade_rc.data.score_normalizer.SharedEncoderService") as MockEnc,
        patch("tier2_screening.hybrid_retriever.HybridRetriever") as MockRet,
    ):
        mock_enc = MockEnc.return_value
        mock_enc.embed_batch.return_value = [np.zeros(128)]

        mock_ret = MockRet.return_value

        def _fake_rank(candidates, pico_embedding, pico_query_text=""):
            return [
                MagicMock(
                    candidate=c,
                    bm25_rank=i + 1,
                    dense_rank=i + 1,
                    rrf_score=2.0 / (60 + i + 1),
                )
                for i, c in enumerate(candidates)
            ]

        mock_ret.rank.side_effect = _fake_rank

        result = compute_raw_scores(parquet_path, "test query")

    required = {"pmid", "bm25", "specter2_cos", "raw_score", "y_abstract"}
    missing = required - set(result.columns)
    assert not missing, f"Missing columns: {missing}"
    assert len(result) == n, f"Expected {n} rows, got {len(result)}"
    assert result["raw_score"].notna().all(), "raw_score contains NaN"
