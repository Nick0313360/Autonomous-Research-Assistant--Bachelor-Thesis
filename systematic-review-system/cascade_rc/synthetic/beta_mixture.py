"""
Synthetic data generator matching paper §3 running example.

Generative process:
  π = 0.05 (prevalence of positives)
  negatives:  s ~ Beta(2, 8)
  positives:  s ~ Beta(8, 2)
  utility:    u ~ Beta(5, 5)  (independent of label)
  LLM screener: escalated stratum gets 10% error rate
    - papers with s in [0.3, 0.7] are "escalated"
    - outside that band the LLM is assumed correct
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def generate_paper_running_example(
    n: int = 10_000,
    seed: int = 0,
) -> pd.DataFrame:
    """Return a DataFrame with columns: pmid, s, u, y, llm_y_hat.

    Parameters
    ----------
    n:
        Total number of synthetic papers.
    seed:
        NumPy random seed for reproducibility.

    Returns
    -------
    pd.DataFrame with columns:
        pmid       int      surrogate identifier
        s          float64  retrieval/relevance score in [0, 1]
        u          float64  utility score in [0, 1]
        y          int      true binary label (1 = include)
        llm_y_hat  int      LLM prediction (1 = include)
    """
    rng = np.random.default_rng(seed)

    pi = 0.05
    y: np.ndarray = (rng.random(n) < pi).astype(int)

    s = np.where(
        y == 1,
        rng.beta(8, 2, size=n),
        rng.beta(2, 8, size=n),
    )

    u = rng.beta(5, 5, size=n)

    # Escalated stratum: papers where the LLM is uncertain (mid-range scores).
    # LLM error rate = 0.10 on this stratum, perfect elsewhere.
    escalated = (s >= 0.3) & (s <= 0.7)
    flip = escalated & (rng.random(n) < 0.10)
    llm_y_hat = np.where(flip, 1 - y, y).astype(int)

    return pd.DataFrame(
        {
            "pmid": np.arange(1, n + 1, dtype=int),
            "s": s,
            "u": u,
            "y": y,
            "llm_y_hat": llm_y_hat,
        }
    )
