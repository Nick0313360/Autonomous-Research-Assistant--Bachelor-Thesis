# SCRC-I and SCRC-T Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `cascade_rc/baselines/scrc.py` (SCRC class + driver) and `cascade_rc/tests/test_scrc.py` (8 tests) per the approved spec at `docs/superpowers/specs/2026-05-03-scrc-design.md`.

**Architecture:** A single `SCRC(variant, alpha, …)` class with `fit(s, u, y)` / `predict(s, u)` interface wraps a pure `_crc_threshold()` helper; a `run_sweep()` function applies it across 2 variants × 4 recalls × 6 topics to produce a 48-row parquet schema-compatible with AUTOSTOP and RLStop. Tests are written TDD-style before each implementation step.

**Tech Stack:** Python 3.11, numpy, pandas, pyarrow, scipy (for Beta draws in coverage tests), `cascade_rc.evaluation.metrics.wss_at_recall`.

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `cascade_rc/baselines/scrc.py` | **New** | `_crc_threshold()` pure function; `SCRC` class with `fit`/`predict`; `run_sweep()`; `__main__` CLI |
| `cascade_rc/tests/test_scrc.py` | **New** | 8 tests: unit (4), algorithm (2), coverage simulation (2) |

---

## Task 1: `_crc_threshold` — pure function, unit tests A1–A2

**Files:**
- Create: `cascade_rc/baselines/scrc.py`
- Create: `cascade_rc/tests/test_scrc.py`

- [ ] **Step 1.1: Create the test file with the two unit tests for `_crc_threshold`**

```python
# cascade_rc/tests/test_scrc.py
"""Tests for cascade_rc.baselines.scrc — SCRC-I and SCRC-T baselines."""
from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_synthetic(
    n: int,
    pi: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (s, u, y): relevance scores, utility scores, labels.

    Positives: s ~ Beta(8, 2); negatives: s ~ Beta(2, 8).
    u ~ Beta(5, 5) independent of label.
    """
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < pi).astype(np.int64)
    s = np.where(y == 1, rng.beta(8, 2, size=n), rng.beta(2, 8, size=n))
    u = rng.beta(5, 5, size=n)
    return s, u, y


# ---------------------------------------------------------------------------
# Category A — Unit correctness: _crc_threshold
# ---------------------------------------------------------------------------

def test_crc_threshold_pin() -> None:
    """Pin the conformal quantile formula against two known values.

    pos_scores = [0.1, 0.2, ..., 1.0], n_pos = 10.

    alpha=0.10: k = floor(0.10 * 11) = 1  → pos_scores[1] = 0.2
    alpha=0.05: k = floor(0.05 * 11) = 0  → pos_scores[0] = 0.1
    """
    from cascade_rc.baselines.scrc import _crc_threshold

    pos_scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    assert _crc_threshold(pos_scores, alpha=0.10) == pytest.approx(0.2)
    assert _crc_threshold(pos_scores, alpha=0.05) == pytest.approx(0.1)


def test_crc_threshold_no_positives() -> None:
    """Empty pos_scores → returns 0.0 (accept everything)."""
    from cascade_rc.baselines.scrc import _crc_threshold

    assert _crc_threshold(np.array([]), alpha=0.10) == pytest.approx(0.0)
```

- [ ] **Step 1.2: Run the tests — expect ImportError (module does not exist yet)**

```bash
cd systematic-review-system && venv/bin/python -m pytest cascade_rc/tests/test_scrc.py::test_crc_threshold_pin cascade_rc/tests/test_scrc.py::test_crc_threshold_no_positives -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'cascade_rc.baselines.scrc'`

- [ ] **Step 1.3: Create `scrc.py` with only `_crc_threshold`**

```python
# cascade_rc/baselines/scrc.py
"""Selective Conformal Risk Control (SCRC-I and SCRC-T) baseline.

Reference: Xu, Guo, Wei, "Selective Conformal Risk Control", arXiv:2512.12844
Supporting: Angelopoulos et al., "Conformal Risk Control", arXiv:2208.02814
"""
from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from cascade_rc.evaluation.metrics import wss_at_recall

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]
DEFAULT_RECALLS: list[float] = [0.80, 0.90, 0.95, 1.0]
DEFAULT_VARIANTS: list[str] = ["I", "T"]

_OUTPUT_SCHEMA: dict[str, str] = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "float64",  # always np.nan — see spec §5
}


# ---------------------------------------------------------------------------
# Pure helper
# ---------------------------------------------------------------------------

def _crc_threshold(pos_scores: np.ndarray, alpha: float) -> float:
    """Split-conformal FNR quantile threshold.

    Given calibration positive scores (sorted ascending) and risk level alpha,
    returns lambda_star such that P(s_test < lambda_star | y_test=1) <= alpha
    by the exchangeability argument:
        k = floor(alpha * (n_pos + 1))
        lambda_star = pos_scores[k]

    Edge cases:
    - n_pos == 0: return 0.0 (no information → accept everything)
    - k >= n_pos: return 0.0 (alpha too large for available positives → accept everything)

    Args:
        pos_scores: (n_pos,) array of positive scores, sorted ascending.
        alpha:      Risk level in [0, 1].

    Returns:
        Scalar threshold lambda_star >= 0.
    """
    n_pos = len(pos_scores)
    if n_pos == 0:
        return 0.0
    k = int(math.floor(alpha * (n_pos + 1)))
    if k >= n_pos:
        return 0.0
    return float(pos_scores[k])
```

- [ ] **Step 1.4: Run the tests — expect PASS**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py::test_crc_threshold_pin cascade_rc/tests/test_scrc.py::test_crc_threshold_no_positives -v
```

Expected: `2 passed`

- [ ] **Step 1.5: Commit**

```bash
git add cascade_rc/baselines/scrc.py cascade_rc/tests/test_scrc.py
git commit -m "feat(scrc): add _crc_threshold pure function with unit tests"
```

---

## Task 2: `SCRC` class — skeleton, pre-fit guard, predict schema (tests A3–A4)

**Files:**
- Modify: `cascade_rc/baselines/scrc.py`
- Modify: `cascade_rc/tests/test_scrc.py`

- [ ] **Step 2.1: Add tests A3 and A4 to the test file**

Append to `cascade_rc/tests/test_scrc.py`:

```python
# ---------------------------------------------------------------------------
# Category A — Unit correctness: SCRC class interface
# ---------------------------------------------------------------------------

def test_predict_before_fit_raises() -> None:
    """predict() raises RuntimeError on an unfitted SCRC instance."""
    from cascade_rc.baselines.scrc import SCRC

    scrc = SCRC(variant="I", alpha=0.10)
    with pytest.raises(RuntimeError, match="fit"):
        scrc.predict(np.array([0.5]), np.array([0.5]))


def test_predict_schema() -> None:
    """predict() returns object array with values only in {'accept','abstain'}."""
    from cascade_rc.baselines.scrc import SCRC

    rng = np.random.default_rng(42)
    n = 50
    s = rng.random(n)
    u = rng.random(n)
    y = (rng.random(n) < 0.2).astype(np.int64)

    for variant in ("I", "T"):
        scrc = SCRC(variant=variant, alpha=0.10)
        scrc.fit(s, u, y)
        decisions = scrc.predict(s, u)
        assert decisions.dtype == object, f"variant={variant}: dtype should be object"
        assert decisions.shape == (n,), f"variant={variant}: wrong shape"
        assert set(decisions).issubset({"accept", "abstain"}), (
            f"variant={variant}: unexpected values {set(decisions)}"
        )
```

- [ ] **Step 2.2: Run — expect FAIL (SCRC not defined)**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py::test_predict_before_fit_raises cascade_rc/tests/test_scrc.py::test_predict_schema -v
```

Expected: `ERROR — ModuleNotFoundError` or `ImportError` (SCRC class missing)

- [ ] **Step 2.3: Add the `SCRC` class to `scrc.py`**

Append to `cascade_rc/baselines/scrc.py` (after `_crc_threshold`):

```python
# ---------------------------------------------------------------------------
# SCRC class
# ---------------------------------------------------------------------------

class SCRC:
    """Selective Conformal Risk Control for TAR document screening.

    Two variants:
      "I" (inductive)  — splits calibration 50/50; fits tau on C1, lambda_star on C2.
      "T" (transductive) — uses full calibration for both; LOO via n_pos+1 correction.

    Usage::

        scrc = SCRC(variant="I", alpha=0.10)
        scrc.fit(s_cal, u_cal, y_cal)
        decisions = scrc.predict(s_test, u_test)   # "accept" | "abstain"

    Fitted attributes (available after fit()):
        tau_         — selection threshold on u; abstain if u < tau_
        lambda_star_ — CRC acceptance threshold on s; accept if s >= lambda_star_
        n_pos_used_  — calibration positives used for lambda_star_ (diagnostic)
    """

    def __init__(
        self,
        variant: Literal["I", "T"],
        alpha: float,
        abstain_rate: float = 0.1,
        split_ratio: float = 0.5,
        seed: int = 0,
    ) -> None:
        if variant not in ("I", "T"):
            raise ValueError(f"variant must be 'I' or 'T', got {variant!r}")
        if not (0.0 <= alpha <= 1.0):
            raise ValueError(f"alpha must be in [0, 1], got {alpha}")
        if not (0.0 <= abstain_rate < 1.0):
            raise ValueError(f"abstain_rate must be in [0, 1), got {abstain_rate}")
        self.variant = variant
        self.alpha = alpha
        self.abstain_rate = abstain_rate
        self.split_ratio = split_ratio
        self.seed = seed
        # Fitted attributes — set by fit()
        self._fitted = False

    # ------------------------------------------------------------------
    # fit
    # ------------------------------------------------------------------

    def fit(
        self,
        s: np.ndarray,
        u: np.ndarray,
        y: np.ndarray,
    ) -> "SCRC":
        """Fit selection threshold tau_ and CRC threshold lambda_star_.

        Args:
            s: (n,) relevance scores in [0, 1].
            u: (n,) utility/confidence scores in [0, 1].
            y: (n,) binary labels {0, 1}.

        Returns:
            self
        """
        s = np.asarray(s, dtype=np.float64)
        u = np.asarray(u, dtype=np.float64)
        y = np.asarray(y, dtype=np.int64)

        if self.variant == "I":
            self._fit_inductive(s, u, y)
        else:
            self._fit_transductive(s, u, y)

        self._fitted = True
        return self

    def _fit_inductive(
        self, s: np.ndarray, u: np.ndarray, y: np.ndarray
    ) -> None:
        rng = np.random.default_rng(self.seed)

        pos_idx = np.where(y == 1)[0]
        neg_idx = np.where(y == 0)[0]
        rng.shuffle(pos_idx)
        rng.shuffle(neg_idx)

        n_pos_c1 = int(math.floor(len(pos_idx) * self.split_ratio))
        n_neg_c1 = int(math.floor(len(neg_idx) * self.split_ratio))

        c1_idx = np.concatenate([pos_idx[:n_pos_c1], neg_idx[:n_neg_c1]])
        c2_idx = np.concatenate([pos_idx[n_pos_c1:], neg_idx[n_neg_c1:]])

        u_c1 = u[c1_idx]
        s_c2, u_c2, y_c2 = s[c2_idx], u[c2_idx], y[c2_idx]

        self.tau_: float = float(np.quantile(u_c1, self.abstain_rate))
        selected_c2 = u_c2 >= self.tau_
        pos_mask = selected_c2 & (y_c2 == 1)
        pos_scores = np.sort(s_c2[pos_mask])
        self.lambda_star_: float = _crc_threshold(pos_scores, self.alpha)
        self.n_pos_used_: int = int(pos_mask.sum())

    def _fit_transductive(
        self, s: np.ndarray, u: np.ndarray, y: np.ndarray
    ) -> None:
        self.tau_: float = float(np.quantile(u, self.abstain_rate))
        selected = u >= self.tau_
        pos_mask = selected & (y == 1)
        pos_scores = np.sort(s[pos_mask])
        self.lambda_star_: float = _crc_threshold(pos_scores, self.alpha)
        self.n_pos_used_: int = int(pos_mask.sum())

    # ------------------------------------------------------------------
    # predict
    # ------------------------------------------------------------------

    def predict(self, s: np.ndarray, u: np.ndarray) -> np.ndarray:
        """Classify each document as 'accept' or 'abstain'.

        Returns an object-dtype array with values in {"accept", "abstain"}.
        Accepts a document iff u >= tau_ AND s >= lambda_star_.

        Raises:
            RuntimeError: if called before fit().
        """
        if not self._fitted:
            raise RuntimeError(
                "SCRC.predict() called before fit(). Call fit(s, u, y) first."
            )
        s = np.asarray(s, dtype=np.float64)
        u = np.asarray(u, dtype=np.float64)
        accepted = (u >= self.tau_) & (s >= self.lambda_star_)
        return np.where(accepted, "accept", "abstain")
```

- [ ] **Step 2.4: Run tests A3 and A4 — expect PASS**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py::test_predict_before_fit_raises cascade_rc/tests/test_scrc.py::test_predict_schema -v
```

Expected: `2 passed`

- [ ] **Step 2.5: Run all tests so far — expect all 4 pass**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py -v -k "threshold or predict"
```

Expected: `4 passed`

- [ ] **Step 2.6: Commit**

```bash
git add cascade_rc/baselines/scrc.py cascade_rc/tests/test_scrc.py
git commit -m "feat(scrc): add SCRC class with fit/predict and pre-fit guard"
```

---

## Task 3: Algorithm correctness tests B1–B2 (`n_pos_used_`, internal split)

**Files:**
- Modify: `cascade_rc/tests/test_scrc.py`

- [ ] **Step 3.1: Add tests B1 and B2**

Append to `cascade_rc/tests/test_scrc.py`:

```python
# ---------------------------------------------------------------------------
# Category B — Algorithm correctness
# ---------------------------------------------------------------------------

def test_scrc_i_internal_split_pins_tau() -> None:
    """SCRC-I tau_ equals np.quantile(u_C1, abstain_rate) for the known-seed split.

    Also verifies stratified split: n_pos_used_ < total positives in cal
    (C2 has strictly fewer positives than the full calibration set).
    """
    from cascade_rc.baselines.scrc import SCRC

    s_cal, u_cal, y_cal = _make_synthetic(n=300, pi=0.10, seed=0)
    n_pos_full = int((y_cal == 1).sum())

    scrc = SCRC(variant="I", alpha=0.10, abstain_rate=0.1, split_ratio=0.5, seed=0)
    scrc.fit(s_cal, u_cal, y_cal)

    # Recompute C1 indices identically to the implementation
    rng = np.random.default_rng(0)
    pos_idx = np.where(y_cal == 1)[0]
    neg_idx = np.where(y_cal == 0)[0]
    rng.shuffle(pos_idx)
    rng.shuffle(neg_idx)
    import math
    n_pos_c1 = int(math.floor(len(pos_idx) * 0.5))
    n_neg_c1 = int(math.floor(len(neg_idx) * 0.5))
    c1_idx = np.concatenate([pos_idx[:n_pos_c1], neg_idx[:n_neg_c1]])

    expected_tau = float(np.quantile(u_cal[c1_idx], 0.1))
    assert scrc.tau_ == pytest.approx(expected_tau, rel=1e-9)
    assert scrc.n_pos_used_ < n_pos_full, (
        f"SCRC-I should use fewer positives than full cal: "
        f"n_pos_used_={scrc.n_pos_used_} vs full={n_pos_full}"
    )


def test_scrc_t_uses_more_positives_than_scrc_i() -> None:
    """SCRC-T n_pos_used_ > SCRC-I n_pos_used_ on the same calibration set.

    SCRC-T uses the full cal; SCRC-I uses only the C2 half.
    """
    from cascade_rc.baselines.scrc import SCRC

    s_cal, u_cal, y_cal = _make_synthetic(n=300, pi=0.10, seed=1)

    scrc_t = SCRC(variant="T", alpha=0.10, abstain_rate=0.1).fit(s_cal, u_cal, y_cal)
    scrc_i = SCRC(variant="I", alpha=0.10, abstain_rate=0.1, split_ratio=0.5, seed=0).fit(s_cal, u_cal, y_cal)

    assert scrc_t.n_pos_used_ > scrc_i.n_pos_used_, (
        f"SCRC-T n_pos_used_={scrc_t.n_pos_used_} should exceed "
        f"SCRC-I n_pos_used_={scrc_i.n_pos_used_}"
    )
```

- [ ] **Step 3.2: Run tests B1 and B2 — expect PASS**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py::test_scrc_i_internal_split_pins_tau cascade_rc/tests/test_scrc.py::test_scrc_t_uses_more_positives_than_scrc_i -v
```

Expected: `2 passed`

- [ ] **Step 3.3: Commit**

```bash
git add cascade_rc/tests/test_scrc.py
git commit -m "test(scrc): add algorithm correctness tests B1-B2 (n_pos_used_, tau pins)"
```

---

## Task 4: Coverage simulation tests C1–C2 (1 000 trials)

**Files:**
- Modify: `cascade_rc/tests/test_scrc.py`

- [ ] **Step 4.1: Add coverage simulation tests C1 and C2**

Append to `cascade_rc/tests/test_scrc.py`:

```python
# ---------------------------------------------------------------------------
# Category C — Coverage simulation (1 000 trials)
# ---------------------------------------------------------------------------

def _run_coverage_trial(
    variant: str,
    alpha: float,
    abstain_rate: float,
    rng: np.random.Generator,
) -> tuple[bool, float]:
    """Single trial: generate data, fit SCRC, return (covered, accept_rate)."""
    from cascade_rc.baselines.scrc import SCRC

    n_cal, n_test, pi = 300, 200, 0.10
    seed = int(rng.integers(0, 2**31))

    s_all, u_all, y_all = _make_synthetic(n=n_cal + n_test, pi=pi, seed=seed)
    s_cal, u_cal, y_cal = s_all[:n_cal], u_all[:n_cal], y_all[:n_cal]
    s_test, u_test, y_test = s_all[n_cal:], u_all[n_cal:], y_all[n_cal:]

    scrc = SCRC(variant=variant, alpha=alpha, abstain_rate=abstain_rate)
    scrc.fit(s_cal, u_cal, y_cal)
    decisions = scrc.predict(s_test, u_test)

    accepted = decisions == "accept"
    n_pos_test = int((y_test == 1).sum())
    recall = float((accepted & (y_test == 1)).sum()) / max(1, n_pos_test)
    covered = recall >= 1.0 - alpha
    accept_rate = float(accepted.mean())
    return covered, accept_rate


@pytest.mark.parametrize("variant", ["I", "T"])
def test_scrc_marginal_coverage_1000(variant: str) -> None:
    """SCRC achieves marginal recall >= 1 - alpha in >= 1 - alpha - 0.02 of 1000 trials.

    Tolerance derivation: binomial 95% CI on true coverage 0.90 at n=1000 trials
    is approximately [0.881, 0.919]. The -0.02 band matches the CI lower bound;
    the assertion fails only when true coverage is genuinely below 0.88.

    Synthetic data: n_cal=300, n_test=200, pi=0.10, positives Beta(8,2),
    negatives Beta(2,8), u ~ Beta(5,5) independent.
    """
    alpha = 0.10
    abstain_rate = 0.10
    n_trials = 1_000
    rng = np.random.default_rng(42)

    covered_list = []
    accept_rates = []
    for _ in range(n_trials):
        covered, accept_rate = _run_coverage_trial(variant, alpha, abstain_rate, rng)
        covered_list.append(covered)
        accept_rates.append(accept_rate)

    empirical_coverage = sum(covered_list) / n_trials
    mean_accept_rate = float(np.mean(accept_rates))

    # Sanity: not degenerate (not all accept, not all abstain)
    assert 0.05 < mean_accept_rate < 0.95, (
        f"variant={variant}: degenerate accept rate {mean_accept_rate:.3f} "
        "(expected 0.05 < rate < 0.95)"
    )

    assert empirical_coverage >= 1.0 - alpha - 0.02, (
        f"variant={variant}: empirical coverage {empirical_coverage:.4f} < "
        f"{1.0 - alpha - 0.02:.4f} (1 - alpha - 0.02 = {1.0 - alpha - 0.02:.4f})"
    )
```

- [ ] **Step 4.2: Run coverage tests — expect PASS (takes ~30–60 s)**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py::test_scrc_marginal_coverage_1000 -v
```

Expected: `2 passed` (parametrised over I and T)

- [ ] **Step 4.3: Run the full test file — all 8 tests green**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py -v
```

Expected: `8 passed` (4 unit + 2 algorithm + 2 coverage)

- [ ] **Step 4.4: Commit**

```bash
git add cascade_rc/tests/test_scrc.py
git commit -m "test(scrc): add coverage simulation tests C1-C2 (1000 trials, I and T)"
```

---

## Task 5: `run_sweep` driver and CLI

**Files:**
- Modify: `cascade_rc/baselines/scrc.py`

- [ ] **Step 5.1: Add `run_sweep`, `_empty_df`, `_build_arg_parser`, and `__main__` to `scrc.py`**

Append to `cascade_rc/baselines/scrc.py`:

```python
# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(
        {col: pd.Series(dtype=dt) for col, dt in _OUTPUT_SCHEMA.items()}
    )


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics: list[str] = DEFAULT_TOPICS,
    recalls: list[float] = DEFAULT_RECALLS,
    variants: list[str] = DEFAULT_VARIANTS,
    abstain_rate: float = 0.1,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run SCRC sweep and write scrc_results.parquet to out_dir.

    Args:
        data_dir:     Directory containing per-topic parquets with columns
                      pmid, s, u, y_abstract, is_calib.
        out_dir:      Output directory; scrc_results.parquet written here.
        topics:       List of topic IDs to process.
        recalls:      List of target recall levels (alpha = 1 - recall).
        variants:     List of SCRC variants to run ("I", "T").
        abstain_rate: Quantile of u used for abstention threshold tau.
        dry_run:      If True, write 0-row schema parquet without fitting.

    Returns:
        DataFrame with 8 columns per _OUTPUT_SCHEMA (48 rows if all defaults).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df = _empty_df()
        df.to_parquet(out_dir / "scrc_results.parquet", index=False)
        logger.info("DRY-RUN: 0-row schema parquet written to %s", out_dir)
        return df

    available = [t for t in topics if (data_dir / f"{t}.parquet").exists()]
    if not available:
        raise FileNotFoundError(f"No topic parquets found in {data_dir}")
    skipped = set(topics) - set(available)
    if skipped:
        logger.warning("Skipping topics (parquet not found): %s", sorted(skipped))

    rows: list[dict] = []
    for variant in variants:
        method = f"scrc_{variant.lower()}"
        for target_recall in recalls:
            alpha = 1.0 - target_recall
            for topic_id in available:
                df_topic = pd.read_parquet(data_dir / f"{topic_id}.parquet")
                cal = df_topic[df_topic["is_calib"] == 1]
                test = df_topic[df_topic["is_calib"] == 0]

                scrc = SCRC(variant=variant, alpha=alpha, abstain_rate=abstain_rate)
                scrc.fit(
                    cal["s"].to_numpy(dtype=np.float64),
                    cal["u"].to_numpy(dtype=np.float64),
                    cal["y_abstract"].to_numpy(dtype=np.int64),
                )
                decisions = scrc.predict(
                    test["s"].to_numpy(dtype=np.float64),
                    test["u"].to_numpy(dtype=np.float64),
                )

                examined = int((decisions == "accept").sum())
                predictions = (decisions == "accept").astype(np.int64)
                y_true = test["y_abstract"].to_numpy(dtype=np.int64)
                wss = wss_at_recall(predictions, y_true, target_recall=0.95)

                row: dict = {
                    "method":          method,
                    "topic_id":        topic_id,
                    "target_recall":   float(target_recall),
                    "examined":        examined,
                    "recall_achieved": float(wss["achieved_recall"])
                                       if wss["achieved_recall"] == wss["achieved_recall"]
                                       else float("nan"),
                    "wss_95":          float(wss["wss"])
                                       if wss["wss"] == wss["wss"]
                                       else float("nan"),
                    "wss_status":      wss["status"],
                    # peak_rss_kb is always NaN: SCRC has constant per-cell memory cost.
                    # Column retained for pd.concat schema parity with AUTOSTOP/RLStop.
                    "peak_rss_kb":     float("nan"),
                }
                rows.append(row)
                logger.info(
                    "SCRC-%s %s @ recall=%.2f  examined=%d  wss_status=%s",
                    variant, topic_id, target_recall, examined, wss["status"],
                )

    df = pd.DataFrame(rows).astype(_OUTPUT_SCHEMA)
    out_path = out_dir / "scrc_results.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows to %s", len(df), out_path)
    return df


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run SCRC-I and SCRC-T baseline sweep.")
    p.add_argument("--data-dir",     type=Path, default=Path("artefacts/cascade_rc/data"))
    p.add_argument("--out-dir",      type=Path, default=Path("artefacts/baselines/scrc"))
    p.add_argument("--topics",       nargs="+", default=DEFAULT_TOPICS, metavar="TOPIC_ID")
    p.add_argument("--recalls",      nargs="+", type=float, default=DEFAULT_RECALLS, metavar="RECALL")
    p.add_argument("--variants",     nargs="+", default=DEFAULT_VARIANTS, choices=["I", "T"])
    p.add_argument("--abstain-rate", type=float, default=0.1,
                   help="Quantile of u for abstention threshold (default 0.1)")
    p.add_argument("--dry-run",      action="store_true",
                   help="Write 0-row schema parquet without fitting models.")
    return p


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _build_arg_parser().parse_args()
    run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        topics=args.topics,
        recalls=args.recalls,
        variants=args.variants,
        abstain_rate=args.abstain_rate,
        dry_run=args.dry_run,
    )
```

- [ ] **Step 5.2: Add driver tests to `test_scrc.py` (dry-run + no-parquets-raises)**

Append to `cascade_rc/tests/test_scrc.py`:

```python
# ---------------------------------------------------------------------------
# Category D — Driver (run_sweep)
# ---------------------------------------------------------------------------

def test_dry_run_zero_rows_correct_schema(tmp_path: "Path") -> None:
    from cascade_rc.baselines.scrc import run_sweep

    df = run_sweep(
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        dry_run=True,
    )
    _SCHEMA = {
        "method":          "object",
        "topic_id":        "object",
        "target_recall":   "float64",
        "examined":        "int64",
        "recall_achieved": "float64",
        "wss_95":          "float64",
        "wss_status":      "object",
        "peak_rss_kb":     "float64",
    }
    assert len(df) == 0
    for col, dtype in _SCHEMA.items():
        assert col in df.columns, f"Missing column: {col}"
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"


def test_dry_run_parquet_written(tmp_path: "Path") -> None:
    from cascade_rc.baselines.scrc import run_sweep

    out_dir = tmp_path / "out"
    run_sweep(data_dir=tmp_path / "data", out_dir=out_dir, dry_run=True)
    assert (out_dir / "scrc_results.parquet").exists()


def test_no_parquets_raises(tmp_path: "Path") -> None:
    from cascade_rc.baselines.scrc import run_sweep

    with pytest.raises(FileNotFoundError):
        run_sweep(data_dir=tmp_path / "empty", out_dir=tmp_path / "out")
```

- [ ] **Step 5.3: Run full test suite — expect all tests pass**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py -v
```

Expected: `11 passed` (original 8 + 3 driver tests)

- [ ] **Step 5.4: Smoke-test `--dry-run` from CLI**

```bash
venv/bin/python -m cascade_rc.baselines.scrc --dry-run --out-dir /tmp/scrc_smoke
```

Expected:
```
INFO:cascade_rc.baselines.scrc:DRY-RUN: 0-row schema parquet written to /tmp/scrc_smoke
```
Verify file exists:
```bash
python3 -c "import pandas as pd; df = pd.read_parquet('/tmp/scrc_smoke/scrc_results.parquet'); print(df.dtypes)"
```
Expected: 8 columns with correct dtypes, 0 rows.

- [ ] **Step 5.5: Commit**

```bash
git add cascade_rc/baselines/scrc.py cascade_rc/tests/test_scrc.py
git commit -m "feat(scrc): add run_sweep driver + CLI + dry-run; driver tests"
```

---

## Task 6: Final verification — all tests, concat parity

**Files:** none new

- [ ] **Step 6.1: Run the complete test suite for the new module**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_scrc.py -v
```

Expected: all 11 tests pass (no failures, no errors).

- [ ] **Step 6.2: Verify schema concat parity with AUTOSTOP and RLStop**

```bash
venv/bin/python -c "
import pandas as pd, numpy as np
from cascade_rc.baselines.scrc import _empty_df as scrc_empty
from cascade_rc.baselines.run_autostop import _empty_df as autostop_empty
from cascade_rc.baselines.run_rlstop import _empty_df as rlstop_empty

a = autostop_empty()
r = rlstop_empty()
s = scrc_empty()

# pd.concat upcasts int64 peak_rss_kb to float64 when SCRC has NaN — expected
combined = pd.concat([a, r, s], ignore_index=True)
assert len(combined) == 0
assert 'method' in combined.columns
print('Schema parity OK. Combined columns:', list(combined.columns))
"
```

Expected output: `Schema parity OK. Combined columns: ['method', 'topic_id', ...]`

- [ ] **Step 6.3: Run full baseline test suite to confirm no regressions**

```bash
venv/bin/python -m pytest cascade_rc/tests/test_autostop_driver.py cascade_rc/tests/test_rlstop_driver.py cascade_rc/tests/test_scrc.py -v
```

Expected: all 24 tests pass (6 autostop + 5 rlstop + 11 scrc... adjust counts based on actual).

- [ ] **Step 6.4: Final commit**

```bash
git add -p   # review diff before committing
git commit -m "feat(baselines): complete SCRC-I and SCRC-T implementation (Prompt 11.3)"
```
