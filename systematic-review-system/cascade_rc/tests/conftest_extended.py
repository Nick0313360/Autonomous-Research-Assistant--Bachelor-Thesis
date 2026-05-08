"""
Shared test fixtures for CASCADE-RC implementation test suite.
All fixtures use synthetic beta-mixture data (paper §3 running example).
No LLM calls, no disk I/O, no network — tests run in < 60 seconds total.
"""

import numpy as np
import pandas as pd
import pytest
from pathlib import Path


# ─── Synthetic data generators ────────────────────────────────────────────────

def make_synthetic_topic(
    n: int = 1000,
    prevalence: float = 0.05,
    seed: int = 42,
    llm_error_rate: float = 0.10,
    alpha: float = 0.10,
    topic_id: str = "TEST001",
) -> pd.DataFrame:
    """
    Generate synthetic topic data matching paper §3 beta-mixture.

    Negatives: s ~ Beta(2, 8)   (low scores)
    Positives: s ~ Beta(8, 2)   (high scores)
    LLM: error rate 0.10 on escalated stratum
    u:   Beta(5, 5) self-consistency score

    Returns DataFrame with columns:
      pmid, s_raw, s, u, y_abstract, llm_y_hat, is_split
    All columns needed by the full pipeline.
    """
    rng = np.random.default_rng(seed)
    n_pos = max(1, int(n * prevalence))
    n_neg = n - n_pos

    s_neg = rng.beta(2, 8, size=n_neg)
    s_pos = rng.beta(8, 2, size=n_pos)
    s_raw = np.concatenate([s_neg, s_pos])
    y = np.array([0] * n_neg + [1] * n_pos, dtype=np.int8)

    s = s_raw.copy()
    u = rng.beta(5, 5, size=n)

    llm_y_hat = y.copy()
    pos_idx = np.where(y == 1)[0]
    n_errors = int(len(pos_idx) * llm_error_rate)
    error_idx = rng.choice(pos_idx, size=n_errors, replace=False)
    llm_y_hat[error_idx] = 0

    pmids = [f"{topic_id}_{i:05d}" for i in range(n)]

    df = pd.DataFrame({
        "pmid": pmids,
        "s_raw": s_raw,
        "s": s,
        "u": u,
        "y_abstract": y,
        "llm_y_hat": llm_y_hat,
        "is_split": -1,
    })

    from cascade_rc.data.splits import three_way_split
    return three_way_split(df, seed=seed)


def make_certified_topic(
    n: int = 2000,
    prevalence: float = 0.08,
    seed: int = 123,
    alpha: float = 0.10,
    delta_eta: float = 0.03,
    delta_ltt: float = 0.07,
) -> tuple[pd.DataFrame, dict]:
    """
    Generate synthetic data AND run full calibration on it.
    Returns (df, calibration_result) for testing the full pipeline.
    This is the integration test fixture — runs in ~5 seconds.
    """
    df = make_synthetic_topic(n=n, prevalence=prevalence, seed=seed)

    from cascade_rc.calibration.main_calibrate import run_calibration
    result = run_calibration(
        df=df,
        topic_id="TEST_CERT",
        alpha=alpha,
        delta_eta=delta_eta,
        delta_ltt=delta_ltt,
        artefact_dir=Path("/tmp/cascade_rc_test"),
        save_certificate=False,
    )
    return df, result


# ─── Pytest fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def synthetic_df_small() -> pd.DataFrame:
    """Small synthetic topic: 500 abstracts, π=0.10. Fast for unit tests."""
    return make_synthetic_topic(n=500, prevalence=0.10, seed=42)


@pytest.fixture(scope="session")
def synthetic_df_medium() -> pd.DataFrame:
    """Medium synthetic topic: 2000 abstracts, π=0.05. Mimics paper §3."""
    return make_synthetic_topic(n=2000, prevalence=0.05, seed=42)


@pytest.fixture(scope="session")
def synthetic_df_degenerate() -> pd.DataFrame:
    """
    Degenerate topic: all s-scores clustered in [0.02, 0.04].
    Mimics CD008874's flat score distribution.
    Used to test that the τ_SE fix works even on bad data.
    """
    rng = np.random.default_rng(99)
    n = 1000
    n_pos = 50
    s = np.concatenate([
        rng.uniform(0.023, 0.040, size=n - n_pos),
        rng.uniform(0.025, 0.054, size=n_pos),
    ])
    u = rng.beta(5, 5, size=n)
    y = np.array([0] * (n - n_pos) + [1] * n_pos, dtype=np.int8)
    llm_y_hat = y.copy()

    df = pd.DataFrame({
        "pmid": [f"DEG_{i}" for i in range(n)],
        "s_raw": s, "s": s, "u": u,
        "y_abstract": y, "llm_y_hat": llm_y_hat,
        "is_split": -1,
    })
    from cascade_rc.data.splits import three_way_split
    return three_way_split(df, seed=42)


@pytest.fixture(scope="session")
def certified_result() -> tuple[pd.DataFrame, dict]:
    """
    Full calibration result on the medium synthetic topic.
    Cached at session scope — computed once, reused across all tests.
    """
    return make_certified_topic(n=2000, prevalence=0.05, seed=42)


@pytest.fixture
def alpha_values() -> list[float]:
    return [0.01, 0.02, 0.05, 0.10, 0.15, 0.20]


@pytest.fixture
def nmin_at_alpha_010() -> int:
    """N_min = 26 at α=0.10, δ_LTT=0.07"""
    return 26
