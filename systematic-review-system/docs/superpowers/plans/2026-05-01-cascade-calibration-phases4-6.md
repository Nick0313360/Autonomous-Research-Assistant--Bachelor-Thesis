# CASCADE-RC Phases 4–6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Algorithm 1 (paper §5.4) — wire calibration phases 4–6 into `calibrate()` with corrected slack, checkpointing, and certificate persistence.

**Architecture:** `main_calibrate.py` orchestrates the 10-step algorithm using existing primitives (`loss_tensor`, `slack_tensor`, `wsr_lcb_one_sided`, `hb_pvalues`, `walk_reject`). `certificates/store.py` handles pickle+JSON persistence with partial-checkpoint support. Chunked joblib parallelism (500 grid points/chunk) provides WSR checkpointing.

**Tech Stack:** Python 3.11, numpy, pandas (parquet), joblib, existing `cascade_rc.calibration.*` primitives, pickle, json.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `cascade_rc/config.py` | Add `c_human`, `c_llm` to `LTTBudget` |
| Modify | `cascade_rc/calibration/surrogate_loss.py` | Add `slack_tensor()` |
| Create | `cascade_rc/certificates/__init__.py` | Package init (empty) |
| Create | `cascade_rc/certificates/store.py` | `CertificationResult` + `CertificateStore` |
| Create | `cascade_rc/calibration/main_calibrate.py` | `calibrate()` + `_compute_n_min()` + `_compute_eta_lcb_chunked()` + `_expected_cost()` + CLI |
| Create | `cascade_rc/tests/test_store.py` | Round-trip tests for store.py |
| Modify | `cascade_rc/tests/test_loss.py` | Add `test_slack_tensor_values`, `test_slack_non_negative_bounded_by_dominating_loss` |
| Create | `cascade_rc/tests/test_main_calibrate_synthetic.py` | 3 required tests |

---

### Task 1: Add cost parameters to LTTBudget

**Files:**
- Modify: `cascade_rc/config.py`

- [ ] **Step 1: Add `c_human` and `c_llm` fields to `LTTBudget`**

Open `cascade_rc/config.py`. After the `N_min_formula` field, add:

```python
class LTTBudget(BaseModel):
    alpha: float = 0.10
    delta_total: float = 0.10
    delta_eta: float = 0.03
    delta_LTT: float = 0.07
    K: int = 20
    B: int = 5
    ensemble_temperature: float = 0.7
    N_min_formula: str = "ceil(ln(1/delta_LTT)/(-ln(1-alpha)))"
    c_human: float = 5.0    # cost of human review (~5 min Cochrane review at $60/h)
    c_llm: float = 0.001    # cost of gpt-oss:120b inference
```

- [ ] **Step 2: Verify the model still validates**

```bash
cd systematic-review-system
python -c "from cascade_rc.config import LTTBudget; b = LTTBudget(); print(b.c_human, b.c_llm)"
```

Expected output: `5.0 0.001`

- [ ] **Step 3: Commit**

```bash
git add cascade_rc/config.py
git commit -m "feat(config): add c_human=5.0, c_llm=0.001 to LTTBudget"
```

---

### Task 2: Add `slack_tensor()` to surrogate_loss.py

**Files:**
- Modify: `cascade_rc/calibration/surrogate_loss.py`
- Modify: `cascade_rc/tests/test_loss.py`

- [ ] **Step 1: Write two failing tests — append to `cascade_rc/tests/test_loss.py`**

```python
# ---------------------------------------------------------------------------
# test_slack_tensor_values
# ---------------------------------------------------------------------------

def test_slack_tensor_values() -> None:
    """η_i = 1 only in uncertain zone with SE firing and LLM correct (y_hat==1).

    Grid point: λ_lo=0.3, λ_hi=0.7, τ_SE=0.5.
    Paper cases:
      idx 0: s=0.1 < λ_lo            → L̃=1, L=1, η=0
      idx 1: s=0.5, u=0.6≥τ_SE, ŷ=1 → L̃=1, L=0, η=1  (uncertain+SE+correct)
      idx 2: s=0.5, u=0.6≥τ_SE, ŷ=0 → L̃=1, L=1, η=0  (uncertain+SE+wrong)
      idx 3: s=0.5, u=0.4<τ_SE       → L̃=0, L=0, η=0  (uncertain, SE silent)
      idx 4: s=0.9 ≥ λ_hi            → L̃=0, L=0, η=0  (auto-include)
    """
    from cascade_rc.calibration.surrogate_loss import slack_tensor

    theta = np.array([[0.3, 0.7, 0.5]])  # (1, 3)
    s_pos = np.array([0.1, 0.5, 0.5, 0.5, 0.9])
    u_pos = np.array([0.6, 0.6, 0.6, 0.4, 0.6])
    y_hat = np.array([1,   1,   0,   1,   1])

    slack = slack_tensor(theta, s_pos, u_pos, y_hat)

    assert slack.shape == (1, 5)
    np.testing.assert_array_equal(slack[0], [0, 1, 0, 0, 0])


# ---------------------------------------------------------------------------
# test_slack_non_negative_bounded_by_dominating_loss
# ---------------------------------------------------------------------------

def test_slack_non_negative_bounded_by_dominating_loss() -> None:
    """0 ≤ η_i(θ) ≤ L̃_i(θ) for all (θ, i) — Lemma 1 of the paper."""
    from cascade_rc.calibration.surrogate_loss import grid, loss_tensor, slack_tensor

    rng = np.random.default_rng(42)
    theta_g = grid(10)
    n = 200
    s = rng.uniform(0.0, 1.0, n)
    u = rng.uniform(0.0, 1.0, n)
    y_hat = rng.integers(0, 2, n)

    L_tilde = loss_tensor(theta_g, s, u).astype(np.float64)
    eta = slack_tensor(theta_g, s, u, y_hat).astype(np.float64)

    assert (eta >= 0).all(), "slack must be non-negative"
    assert (eta <= L_tilde).all(), "slack cannot exceed dominating loss"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_loss.py::test_slack_tensor_values cascade_rc/tests/test_loss.py::test_slack_non_negative_bounded_by_dominating_loss -v
```

Expected: `ImportError: cannot import name 'slack_tensor'`

- [ ] **Step 3: Implement `slack_tensor()` — append to `cascade_rc/calibration/surrogate_loss.py`**

```python
def slack_tensor(
    theta_grid: np.ndarray,
    s_pos: np.ndarray,
    u_pos: np.ndarray,
    y_hat_pos: np.ndarray,
) -> np.ndarray:
    """Slack η_i(θ) = L̃_i(θ) − L_i(θ) for each (grid point, calibration positive).

    η_i = 1 iff paper is in the uncertain zone, the second screener fires,
    and the LLM verdict was correct (y_hat==1). Zero otherwise (Lemma 1).

    Args:
        theta_grid: (G, 3) array of (λ_lo, λ_hi, τ_SE) candidates.
        s_pos:      (n_pos,) relevance scores for positive examples.
        u_pos:      (n_pos,) second-screener scores for the same examples.
        y_hat_pos:  (n_pos,) LLM verdicts (1 = include, 0 = exclude).

    Returns:
        uint8 array of shape (G, n_pos); entry [g, i] = 1 when η_i(θ_g) = 1.
    """
    lam_lo = theta_grid[:, 0:1]          # (G, 1)
    lam_hi = theta_grid[:, 1:2]          # (G, 1)
    tau_se = theta_grid[:, 2:3]          # (G, 1)

    s = s_pos[np.newaxis, :]             # (1, n_pos)
    u = u_pos[np.newaxis, :]             # (1, n_pos)
    y_hat = y_hat_pos[np.newaxis, :]     # (1, n_pos)

    in_uncertain = (lam_lo <= s) & (s < lam_hi)   # (G, n_pos)
    se_fires = u >= tau_se                          # (G, n_pos)
    llm_correct = y_hat == 1                        # (1, n_pos)

    return (in_uncertain & se_fires & llm_correct).view(np.uint8)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_loss.py::test_slack_tensor_values cascade_rc/tests/test_loss.py::test_slack_non_negative_bounded_by_dominating_loss -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/calibration/surrogate_loss.py cascade_rc/tests/test_loss.py
git commit -m "feat(surrogate_loss): add slack_tensor() for corrected η_i = L̃_i − L_i"
```

---

### Task 3: Create `cascade_rc/certificates/store.py`

**Files:**
- Create: `cascade_rc/certificates/__init__.py`
- Create: `cascade_rc/certificates/store.py`
- Create: `cascade_rc/tests/test_store.py`

- [ ] **Step 1: Write failing tests in `cascade_rc/tests/test_store.py`**

```python
"""Tests for CertificationResult persistence (certificates/store.py)."""
from __future__ import annotations

import pickle
import json
from pathlib import Path

import numpy as np
import pytest

from cascade_rc.certificates.store import CertificationResult, CertificateStore


def _make_result(topic: str = "CD000001") -> CertificationResult:
    G = 10
    return CertificationResult(
        topic=topic,
        status="certified",
        abstain_reason=None,
        m_plus=42,
        theta_hat=np.array([0.2, 0.6, 0.4]),
        lambda_hat_mask=np.ones(G, dtype=bool),
        theta_grid=np.zeros((G, 3)),
        eta_lcb_grid=np.zeros(G),
        r_hat_grid=np.zeros(G),
        p_hb_grid=np.zeros(G),
        alpha_dagger_grid=np.zeros(G),
        config_snapshot={"alpha": 0.10},
        timestamp="2026-05-01T00:00:00+00:00",
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    """Saved CertificationResult loads back bytes-identical."""
    result = _make_result()
    CertificateStore.save("CD000001", result, tmp_path)

    pkl_path = tmp_path / "certificates" / "CD000001.pkl"
    json_path = tmp_path / "certificates" / "CD000001.json"
    assert pkl_path.exists(), "pickle file should exist"
    assert json_path.exists(), "json summary should exist"

    loaded = CertificateStore.load("CD000001", tmp_path)
    assert loaded.topic == result.topic
    assert loaded.m_plus == result.m_plus
    np.testing.assert_array_equal(loaded.theta_hat, result.theta_hat)
    np.testing.assert_array_equal(loaded.lambda_hat_mask, result.lambda_hat_mask)


def test_json_summary_keys(tmp_path: Path) -> None:
    """JSON summary contains required human-readable fields."""
    CertificateStore.save("CD000001", _make_result(), tmp_path)
    with open(tmp_path / "certificates" / "CD000001.json") as f:
        summary = json.load(f)
    for key in ("topic", "status", "m_plus", "timestamp", "n_certified", "theta_hat"):
        assert key in summary, f"Missing key: {key}"


def test_partial_save_load_delete(tmp_path: Path) -> None:
    """Partial checkpoint persists and is deleted cleanly."""
    state = {"grid_idx_completed": 500, "eta_lcb_partial": np.zeros(500)}
    CertificateStore.save_partial("CD000001", state, tmp_path)

    partial_path = tmp_path / "certificates" / "CD000001.partial.pkl"
    assert partial_path.exists()

    loaded = CertificateStore.load_partial("CD000001", tmp_path)
    assert loaded["grid_idx_completed"] == 500
    np.testing.assert_array_equal(loaded["eta_lcb_partial"], np.zeros(500))

    CertificateStore.delete_partial("CD000001", tmp_path)
    assert not partial_path.exists()
    assert CertificateStore.load_partial("CD000001", tmp_path) is None
```

- [ ] **Step 2: Run to confirm they fail**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'cascade_rc.certificates'`

- [ ] **Step 3: Create `cascade_rc/certificates/__init__.py`**

```bash
touch systematic-review-system/cascade_rc/certificates/__init__.py
```

- [ ] **Step 4: Create `cascade_rc/certificates/store.py`**

```python
"""Persistence layer for CASCADE-RC certification results."""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class CertificationResult:
    topic: str
    status: str                        # "certified" | "abstained"
    abstain_reason: str | None
    m_plus: int
    theta_hat: np.ndarray              # (3,) optimal θ̂ = (λ_lo, λ_hi, τ_SE)
    lambda_hat_mask: np.ndarray        # (G,) bool; True = certified
    theta_grid: np.ndarray             # (G, 3)
    eta_lcb_grid: np.ndarray           # (G,) η̂⁻⋆
    r_hat_grid: np.ndarray             # (G,) R̂
    p_hb_grid: np.ndarray             # (G,) p_HB
    alpha_dagger_grid: np.ndarray      # (G,) α†
    config_snapshot: dict
    timestamp: str                     # ISO-8601


class CertificateStore:
    @staticmethod
    def _cert_dir(artefact_dir: Path) -> Path:
        d = artefact_dir / "certificates"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def _pkl_path(cls, topic: str, artefact_dir: Path) -> Path:
        return cls._cert_dir(artefact_dir) / f"{topic}.pkl"

    @classmethod
    def _json_path(cls, topic: str, artefact_dir: Path) -> Path:
        return cls._cert_dir(artefact_dir) / f"{topic}.json"

    @classmethod
    def _partial_path(cls, topic: str, artefact_dir: Path) -> Path:
        return cls._cert_dir(artefact_dir) / f"{topic}.partial.pkl"

    @classmethod
    def save(
        cls, topic: str, result: CertificationResult, artefact_dir: Path
    ) -> tuple[Path, Path]:
        pkl_path = cls._pkl_path(topic, artefact_dir)
        json_path = cls._json_path(topic, artefact_dir)

        with open(pkl_path, "wb") as f:
            pickle.dump(result, f)

        summary = {
            "topic": result.topic,
            "status": result.status,
            "abstain_reason": result.abstain_reason,
            "m_plus": result.m_plus,
            "timestamp": result.timestamp,
            "n_certified": int(result.lambda_hat_mask.sum()),
            "theta_hat": result.theta_hat.tolist() if result.theta_hat is not None else None,
            "config_snapshot": result.config_snapshot,
        }
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2)

        return pkl_path, json_path

    @classmethod
    def load(cls, topic: str, artefact_dir: Path) -> CertificationResult:
        with open(cls._pkl_path(topic, artefact_dir), "rb") as f:
            return pickle.load(f)

    @classmethod
    def save_partial(cls, topic: str, state: dict, artefact_dir: Path) -> Path:
        partial_path = cls._partial_path(topic, artefact_dir)
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        with open(partial_path, "wb") as f:
            pickle.dump(state, f)
        return partial_path

    @classmethod
    def load_partial(cls, topic: str, artefact_dir: Path) -> dict | None:
        partial_path = cls._partial_path(topic, artefact_dir)
        if not partial_path.exists():
            return None
        with open(partial_path, "rb") as f:
            return pickle.load(f)

    @classmethod
    def delete_partial(cls, topic: str, artefact_dir: Path) -> None:
        partial_path = cls._partial_path(topic, artefact_dir)
        if partial_path.exists():
            partial_path.unlink()
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_store.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add cascade_rc/certificates/__init__.py cascade_rc/certificates/store.py cascade_rc/tests/test_store.py
git commit -m "feat(certificates): add CertificationResult dataclass and CertificateStore"
```

---

### Task 4: Implement `calibrate()` with abstention only

**Files:**
- Create: `cascade_rc/calibration/main_calibrate.py`
- Create: `cascade_rc/tests/test_main_calibrate_synthetic.py` (partial — abstention test only)

- [ ] **Step 1: Write the abstention test in `cascade_rc/tests/test_main_calibrate_synthetic.py`**

```python
"""Tests for main_calibrate.py — Algorithm 1 orchestration.

All tests use cascade_rc.synthetic.beta_mixture for deterministic, reproducible data.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cascade_rc.config import CascadeRCConfig, LTTBudget
from cascade_rc.synthetic.beta_mixture import generate_paper_running_example


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_config(artefact_dir: Path) -> CascadeRCConfig:
    return CascadeRCConfig(
        ltt=LTTBudget(
            alpha=0.10,
            delta_total=0.10,
            delta_eta=0.03,
            delta_LTT=0.07,
            K=20,
        ),
        artefact_dir=artefact_dir,
    )


def _make_calib_parquet(tmp_path: Path, n: int = 10_000, seed: int = 0) -> Path:
    """Generate synthetic data and write a calibration parquet."""
    df = generate_paper_running_example(n=n, seed=seed)
    df = df.rename(columns={"y": "y_abstract"})

    # Stratified 50/50 split
    rng = np.random.default_rng(20260429)
    is_calib = np.zeros(len(df), dtype=int)
    for label in [0, 1]:
        idx = df.index[df["y_abstract"] == label].tolist()
        calib_idx = rng.choice(idx, size=len(idx) // 2, replace=False)
        is_calib[calib_idx] = 1
    df["is_calib"] = is_calib

    parquet_path = tmp_path / "synthetic.parquet"
    df.to_parquet(parquet_path, index=False)
    return parquet_path


# ---------------------------------------------------------------------------
# test_abstention_when_m_plus_below_N_min
# ---------------------------------------------------------------------------

def test_abstention_when_m_plus_below_N_min(tmp_path: Path) -> None:
    """With m_plus=20 < N_min=26 (α=0.10, δ_LTT=0.07), calibrate() abstains.

    N_min = ceil(ln(1/0.07) / (-ln(1-0.10))) = ceil(25.24) = 26.
    We construct a parquet with exactly 20 positive calibration rows.
    """
    from cascade_rc.calibration.main_calibrate import calibrate

    df = generate_paper_running_example(n=2_000, seed=7)
    df = df.rename(columns={"y": "y_abstract"})

    # Force exactly 20 positives in the calibration set
    pos_idx = df.index[df["y_abstract"] == 1].tolist()
    neg_idx = df.index[df["y_abstract"] == 0].tolist()

    is_calib = np.zeros(len(df), dtype=int)
    for i in pos_idx[:20]:
        is_calib[i] = 1
    for i in neg_idx[:200]:
        is_calib[i] = 1
    df["is_calib"] = is_calib

    parquet_path = tmp_path / "small.parquet"
    df.to_parquet(parquet_path, index=False)

    cfg = _make_config(tmp_path)
    result = calibrate("small", parquet_path, cfg)

    assert isinstance(result, tuple), "should return 3-tuple on abstention"
    none_a, none_b, reason = result
    assert none_a is None
    assert none_b is None
    assert reason.startswith("abstained:m_plus=20"), f"unexpected reason: {reason}"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_main_calibrate_synthetic.py::test_abstention_when_m_plus_below_N_min -v
```

Expected: `ModuleNotFoundError: No module named 'cascade_rc.calibration.main_calibrate'`

- [ ] **Step 3: Create `cascade_rc/calibration/main_calibrate.py` — skeleton with abstention**

```python
"""Algorithm 1 orchestrator for CASCADE-RC calibration (paper §5.4).

Entry point:
    python -m cascade_rc.calibration.main_calibrate --topic CD008874 --calib-parquet path/to/file.parquet
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from cascade_rc.calibration.hb_pvalue import hb_pvalues
from cascade_rc.calibration.surrogate_loss import grid as _theta_grid, loss_tensor, slack_tensor
from cascade_rc.calibration.walker import safest_to_riskiest_order, walk_reject
from cascade_rc.calibration.wsr_lcb import wsr_lcb_one_sided
from cascade_rc.certificates.store import CertificationResult, CertificateStore
from cascade_rc.config import CascadeRCConfig


def _compute_n_min(alpha: float, delta_ltt: float) -> int:
    """N_min = ceil(ln(1/δ_LTT) / (-ln(1-α))) — minimum calibration positives required."""
    return math.ceil(math.log(1.0 / delta_ltt) / (-math.log(1.0 - alpha)))


def calibrate(
    topic_id: str,
    calib_parquet: Path,
    config: CascadeRCConfig,
    artefact_dir: Path | None = None,
    chunk_size: int = 500,
) -> "CertificationResult | tuple[None, None, str]":
    """Run Algorithm 1: certify operating point θ̂ for topic_id.

    Args:
        topic_id:       Topic identifier used for artefact naming.
        calib_parquet:  Parquet with columns: pmid, s, u, y_abstract, llm_y_hat, is_calib.
        config:         CascadeRCConfig with LTT budget and artefact paths.
        artefact_dir:   Override for config.artefact_dir.
        chunk_size:     Number of grid points per WSR checkpoint batch.

    Returns:
        CertificationResult on success, or (None, None, reason_str) on abstention.
    """
    if artefact_dir is None:
        artefact_dir = config.artefact_dir

    ltt = config.ltt
    alpha = ltt.alpha
    delta_eta = ltt.delta_eta
    delta_ltt = ltt.delta_LTT
    K = ltt.K
    c_human = ltt.c_human
    c_llm = ltt.c_llm

    # Step 1: Filter calibration positives
    df = pd.read_parquet(calib_parquet)
    df_pos = df[(df["is_calib"] == 1) & (df["y_abstract"] == 1)]
    m_plus = len(df_pos)

    # Step 2: Abstention check
    N_min = _compute_n_min(alpha, delta_ltt)
    if m_plus < N_min:
        return (None, None, f"abstained:m_plus={m_plus}<{N_min}")

    raise NotImplementedError("Full calibration not yet implemented — Task 5")
```

- [ ] **Step 4: Run to confirm the abstention test passes**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_main_calibrate_synthetic.py::test_abstention_when_m_plus_below_N_min -v
```

Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/calibration/main_calibrate.py cascade_rc/tests/test_main_calibrate_synthetic.py
git commit -m "feat(main_calibrate): skeleton with abstention check (_compute_n_min)"
```

---

### Task 5: Implement full Algorithm 1 in `calibrate()`

**Files:**
- Modify: `cascade_rc/calibration/main_calibrate.py`
- Modify: `cascade_rc/tests/test_main_calibrate_synthetic.py`

- [ ] **Step 1: Write the synthetic certification test — append to `test_main_calibrate_synthetic.py`**

```python
# ---------------------------------------------------------------------------
# test_certification_synthetic
# ---------------------------------------------------------------------------

def test_certification_synthetic(tmp_path: Path) -> None:
    """Synthetic running example (n=10_000, seed=0) certifies non-empty Λ̂ for α=0.10.

    θ̂ is pinned to the value computed on first correct run.
    Reference computed 2026-05-01 with K=20, seed=0, split_seed=20260429.
    Tolerance: ±1 grid step per axis (atol = 1/(K-1) ≈ 0.0526).
    """
    from cascade_rc.calibration.main_calibrate import calibrate
    from cascade_rc.certificates.store import CertificationResult

    calib_parquet = _make_calib_parquet(tmp_path)
    cfg = _make_config(tmp_path)
    result = calibrate("synthetic", calib_parquet, cfg)

    assert isinstance(result, CertificationResult)
    assert result.status == "certified"
    assert result.lambda_hat_mask.sum() > 0, "Λ̂ must be non-empty"

    # Pin θ̂ — hardcode after first correct run (see Task 5 Step 5)
    # REFERENCE_THETA_HAT = np.array([...])  # to be filled
    # np.testing.assert_allclose(result.theta_hat, REFERENCE_THETA_HAT, atol=1/19)
```

- [ ] **Step 2: Run to confirm it fails with NotImplementedError**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_main_calibrate_synthetic.py::test_certification_synthetic -v
```

Expected: `FAILED — NotImplementedError: Full calibration not yet implemented`

- [ ] **Step 3: Implement `_expected_cost()` and `_compute_eta_lcb_chunked()`, then complete `calibrate()` — replace `main_calibrate.py` entirely**

```python
"""Algorithm 1 orchestrator for CASCADE-RC calibration (paper §5.4).

Entry point:
    python -m cascade_rc.calibration.main_calibrate --topic CD008874 --calib-parquet path/to/file.parquet
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import Parallel, delayed

from cascade_rc.calibration.hb_pvalue import hb_pvalues
from cascade_rc.calibration.surrogate_loss import grid as _theta_grid, loss_tensor, slack_tensor
from cascade_rc.calibration.walker import safest_to_riskiest_order, walk_reject
from cascade_rc.calibration.wsr_lcb import wsr_lcb_one_sided
from cascade_rc.certificates.store import CertificationResult, CertificateStore
from cascade_rc.config import CascadeRCConfig


def _compute_n_min(alpha: float, delta_ltt: float) -> int:
    """N_min = ceil(ln(1/δ_LTT) / (-ln(1-α))) — minimum calibration positives required."""
    return math.ceil(math.log(1.0 / delta_ltt) / (-math.log(1.0 - alpha)))


def _expected_cost(
    theta_grid: np.ndarray,
    s_all: np.ndarray,
    u_all: np.ndarray,
    c_human: float,
    c_llm: float,
) -> np.ndarray:
    """Expected operating cost for each grid point (§6).

    Estimates P_escalate_no_se and P_escalate_se from calibration data.
    Cost = c_human * P(uncertain zone, SE silent) + c_llm * P(uncertain zone, SE fires).

    Args:
        theta_grid: (G, 3) grid of (λ_lo, λ_hi, τ_SE).
        s_all:      (N,) relevance scores for all is_calib==1 rows.
        u_all:      (N,) second-screener scores for the same rows.
        c_human:    Cost of human review.
        c_llm:      Cost of LLM/SE escalation.

    Returns:
        (G,) array of expected costs.
    """
    lam_lo = theta_grid[:, 0:1]   # (G, 1)
    lam_hi = theta_grid[:, 1:2]   # (G, 1)
    tau_se = theta_grid[:, 2:3]   # (G, 1)

    s = s_all[np.newaxis, :]      # (1, N)
    u = u_all[np.newaxis, :]      # (1, N)

    in_uncertain = (lam_lo <= s) & (s < lam_hi)    # (G, N)
    se_fires = u >= tau_se                           # (G, N)

    p_no_se = (in_uncertain & ~se_fires).mean(axis=1)   # (G,)
    p_se = (in_uncertain & se_fires).mean(axis=1)        # (G,)

    return c_human * p_no_se + c_llm * p_se             # (G,)


def _compute_eta_lcb_chunked(
    slack_mat: np.ndarray,
    delta_eta: float,
    G: int,
    topic: str,
    artefact_dir: Path,
    chunk_size: int = 500,
    resume_from: int = 0,
    resume_eta_lcb: np.ndarray | None = None,
) -> np.ndarray:
    """Compute η̂⁻⋆(θ) for all G grid points with chunked checkpointing.

    Bonferroni level is delta_eta / G regardless of chunk size.
    Every chunk_size evaluations, state is saved to <topic>.partial.pkl.

    Args:
        slack_mat:       (G, m_plus) float64 slack samples.
        delta_eta:       Total slack budget across all grid points.
        G:               Total number of grid points (for Bonferroni).
        topic:           Topic identifier for partial checkpoint naming.
        artefact_dir:    Directory for partial checkpoints.
        chunk_size:      Grid points per checkpoint batch.
        resume_from:     First uncompleted grid index (0 = start fresh).
        resume_eta_lcb:  (G,) array pre-filled for indices < resume_from.

    Returns:
        (G,) array of η̂⁻⋆ values.
    """
    eta_lcb = resume_eta_lcb if resume_eta_lcb is not None else np.zeros(G)
    per_point_delta = delta_eta / G  # Bonferroni over all G points

    for start in range(resume_from, G, chunk_size):
        end = min(start + chunk_size, G)
        chunk_indices = list(range(start, end))
        chunk_lcbs: list[float] = Parallel(n_jobs=-1)(
            delayed(wsr_lcb_one_sided)(
                slack_mat[g].astype(np.float64), delta=per_point_delta
            )
            for g in chunk_indices
        )
        eta_lcb[start:end] = chunk_lcbs
        state = {
            "grid_idx_completed": end,
            "eta_lcb_partial": eta_lcb[:end].copy(),
        }
        CertificateStore.save_partial(topic, state, artefact_dir)

    return eta_lcb


def calibrate(
    topic_id: str,
    calib_parquet: Path,
    config: CascadeRCConfig,
    artefact_dir: Path | None = None,
    chunk_size: int = 500,
) -> "CertificationResult | tuple[None, None, str]":
    """Run Algorithm 1: certify operating point θ̂ for topic_id.

    Args:
        topic_id:       Topic identifier used for artefact naming.
        calib_parquet:  Parquet with columns: pmid, s, u, y_abstract, llm_y_hat, is_calib.
        config:         CascadeRCConfig with LTT budget and artefact paths.
        artefact_dir:   Override for config.artefact_dir.
        chunk_size:     Grid points per WSR checkpoint batch (default 500).

    Returns:
        CertificationResult on success, or (None, None, reason_str) on abstention.
    """
    if artefact_dir is None:
        artefact_dir = config.artefact_dir

    ltt = config.ltt
    alpha = ltt.alpha
    delta_eta = ltt.delta_eta
    delta_ltt = ltt.delta_LTT
    K = ltt.K
    c_human = ltt.c_human
    c_llm = ltt.c_llm

    # Step 1: Filter calibration positives
    df = pd.read_parquet(calib_parquet)
    df_pos = df[(df["is_calib"] == 1) & (df["y_abstract"] == 1)]
    m_plus = len(df_pos)

    # Step 2: Abstention check
    N_min = _compute_n_min(alpha, delta_ltt)
    if m_plus < N_min:
        return (None, None, f"abstained:m_plus={m_plus}<{N_min}")

    s_pos = df_pos["s"].to_numpy(dtype=np.float64)
    u_pos = df_pos["u"].to_numpy(dtype=np.float64)
    y_hat_pos = df_pos["llm_y_hat"].to_numpy(dtype=np.int64)

    df_calib = df[df["is_calib"] == 1]
    s_all = df_calib["s"].to_numpy(dtype=np.float64)
    u_all = df_calib["u"].to_numpy(dtype=np.float64)

    # Step 3: Build K^3 grid (filtered to λ_lo ≤ λ_hi)
    theta_g = _theta_grid(K)    # (G, 3)
    G = len(theta_g)

    # Step 4: Loss and slack matrices (G, m_plus)
    loss_mat = loss_tensor(theta_g, s_pos, u_pos).astype(np.float64)
    slack_mat = slack_tensor(theta_g, s_pos, u_pos, y_hat_pos).astype(np.float64)

    # Resume from partial checkpoint if it exists
    partial = CertificateStore.load_partial(topic_id, artefact_dir)
    resume_from = 0
    resume_eta_lcb: np.ndarray | None = None
    if partial is not None:
        resume_from = partial["grid_idx_completed"]
        padded = np.zeros(G)
        stored = partial["eta_lcb_partial"]
        padded[: len(stored)] = stored
        resume_eta_lcb = padded

    # Compute η̂⁻⋆ with checkpointing
    eta_lcb = _compute_eta_lcb_chunked(
        slack_mat, delta_eta, G, topic_id, artefact_dir,
        chunk_size=chunk_size, resume_from=resume_from, resume_eta_lcb=resume_eta_lcb,
    )

    # Step 5: Empirical risk R̂(θ)
    R_hat = loss_mat.mean(axis=1)    # (G,)

    # Step 6: Corrected level α†(θ) = α + η̂⁻⋆(θ)
    alpha_dagger = alpha + eta_lcb   # (G,)

    # Step 7: HB p-values
    p_hb = hb_pvalues(R_hat, alpha_dagger, n=m_plus)   # (G,)

    # Step 8: Fixed-sequence walk — reject until first acceptance
    order = safest_to_riskiest_order(theta_g)
    lambda_hat_mask = walk_reject(p_hb, order, delta_ltt)   # (G,) bool

    # Step 9: θ̂ = argmin expected_cost over Λ̂
    costs = _expected_cost(theta_g, s_all, u_all, c_human, c_llm)
    certified_costs = np.where(lambda_hat_mask, costs, np.inf)
    theta_hat_idx = int(np.argmin(certified_costs))
    theta_hat = theta_g[theta_hat_idx]

    # Step 10: Persist result and clean up partial
    result = CertificationResult(
        topic=topic_id,
        status="certified",
        abstain_reason=None,
        m_plus=m_plus,
        theta_hat=theta_hat,
        lambda_hat_mask=lambda_hat_mask,
        theta_grid=theta_g,
        eta_lcb_grid=eta_lcb,
        r_hat_grid=R_hat,
        p_hb_grid=p_hb,
        alpha_dagger_grid=alpha_dagger,
        config_snapshot={
            "alpha": alpha,
            "delta_eta": delta_eta,
            "delta_LTT": delta_ltt,
            "K": K,
            "c_human": c_human,
            "c_llm": c_llm,
        },
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    CertificateStore.save(topic_id, result, artefact_dir)
    CertificateStore.delete_partial(topic_id, artefact_dir)

    return result
```

- [ ] **Step 4: Run both tests to confirm they pass**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_main_calibrate_synthetic.py::test_certification_synthetic cascade_rc/tests/test_main_calibrate_synthetic.py::test_abstention_when_m_plus_below_N_min -v
```

Expected: `2 passed`

- [ ] **Step 5: Capture reference θ̂ and hardcode it in the test**

Run:
```bash
cd systematic-review-system
python -c "
import tempfile, numpy as np
from pathlib import Path
from cascade_rc.config import CascadeRCConfig, LTTBudget
from cascade_rc.synthetic.beta_mixture import generate_paper_running_example
from cascade_rc.calibration.main_calibrate import calibrate
import pandas as pd

with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    df = generate_paper_running_example(n=10_000, seed=0).rename(columns={'y': 'y_abstract'})
    rng = np.random.default_rng(20260429)
    is_calib = np.zeros(len(df), dtype=int)
    for label in [0, 1]:
        idx = df.index[df['y_abstract'] == label].tolist()
        is_calib[rng.choice(idx, size=len(idx)//2, replace=False)] = 1
    df['is_calib'] = is_calib
    p = tmp / 'syn.parquet'
    df.to_parquet(p, index=False)
    cfg = CascadeRCConfig(ltt=LTTBudget(alpha=0.10, delta_total=0.10, delta_eta=0.03, delta_LTT=0.07, K=20), artefact_dir=tmp)
    r = calibrate('syn', p, cfg)
    print('theta_hat:', r.theta_hat)
    print('lambda_hat count:', r.lambda_hat_mask.sum())
"
```

Copy the printed `theta_hat` array and replace the commented-out pin in `test_certification_synthetic`:

```python
    # Replace the commented block with actual reference, e.g.:
    REFERENCE_THETA_HAT = np.array([0.XXX, 0.XXX, 0.XXX])  # from first correct run
    np.testing.assert_allclose(result.theta_hat, REFERENCE_THETA_HAT, atol=1.0 / 19)
```

- [ ] **Step 6: Rerun to confirm the pinned assertion passes**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_main_calibrate_synthetic.py::test_certification_synthetic -v
```

Expected: `1 passed`

- [ ] **Step 7: Commit**

```bash
git add cascade_rc/calibration/main_calibrate.py cascade_rc/tests/test_main_calibrate_synthetic.py
git commit -m "feat(main_calibrate): implement full Algorithm 1 with eta_lcb + HB + walk + cost"
```

---

### Task 6: Add resume test for checkpointing

**Files:**
- Modify: `cascade_rc/tests/test_main_calibrate_synthetic.py`

- [ ] **Step 1: Append `test_resume_from_partial` to `test_main_calibrate_synthetic.py`**

```python
# ---------------------------------------------------------------------------
# test_resume_from_partial
# ---------------------------------------------------------------------------

def test_resume_from_partial(tmp_path: Path) -> None:
    """Restarting from a partial checkpoint produces bytes-identical Λ̂.

    Strategy:
    1. Run calibrate() fully (no-checkpoint baseline) → result_full.
    2. Manually construct a partial checkpoint from the first 500 eta_lcb values
       of result_full (simulating a run interrupted after 500 grid evaluations).
    3. Run calibrate() on a fresh topic that sees the planted partial → result_resumed.
    4. Assert lambda_hat_mask bytes-identical between result_full and result_resumed.
    """
    from cascade_rc.calibration.main_calibrate import calibrate
    from cascade_rc.calibration.surrogate_loss import grid as sg
    from cascade_rc.certificates.store import CertificateStore

    calib_parquet = _make_calib_parquet(tmp_path)
    cfg = _make_config(tmp_path)

    G = len(sg(cfg.ltt.K))
    # Step 1: Full run (large chunk so no real checkpoints, clean baseline)
    result_full = calibrate("topic_full", calib_parquet, cfg, chunk_size=G + 1)

    # Step 2: Plant partial checkpoint at grid index 500 for "topic_resume"
    partial_state = {
        "grid_idx_completed": min(500, G),
        "eta_lcb_partial": result_full.eta_lcb_grid[: min(500, G)].copy(),
    }
    CertificateStore.save_partial("topic_resume", partial_state, tmp_path)

    # Step 3: Resume run — should skip indices 0:500 and compute the rest
    result_resumed = calibrate("topic_resume", calib_parquet, cfg, chunk_size=G + 1)

    # Step 4: Λ̂ must be bytes-identical
    assert result_resumed.lambda_hat_mask.tobytes() == result_full.lambda_hat_mask.tobytes(), (
        "Resumed Λ̂ differs from full run — checkpointing is broken"
    )
```

- [ ] **Step 2: Run to confirm it passes**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_main_calibrate_synthetic.py::test_resume_from_partial -v
```

Expected: `1 passed`

- [ ] **Step 3: Run all three required tests together**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_main_calibrate_synthetic.py -v
```

Expected: `3 passed`

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/tests/test_main_calibrate_synthetic.py
git commit -m "test(main_calibrate): add resume_from_partial checkpoint test"
```

---

### Task 7: Add CLI entry point to `main_calibrate.py`

**Files:**
- Modify: `cascade_rc/calibration/main_calibrate.py`

- [ ] **Step 1: Append `main()` and `__main__` guard to `cascade_rc/calibration/main_calibrate.py`**

Add this at the bottom of the file (after the `calibrate()` function):

```python
def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="CASCADE-RC calibration — Algorithm 1",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", required=True, help="Topic identifier, e.g. CD008874")
    parser.add_argument(
        "--calib-parquet", required=True, type=Path,
        help="Path to calibration parquet (columns: pmid,s,u,y_abstract,llm_y_hat,is_calib)",
    )
    parser.add_argument(
        "--artefact-dir", type=Path, default=None,
        help="Override artefact_dir from config",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=500,
        help="Grid points per WSR checkpoint batch",
    )
    args = parser.parse_args()

    cfg = CascadeRCConfig()   # loads from cascade_rc.yaml if present, else defaults

    result = calibrate(
        topic_id=args.topic,
        calib_parquet=args.calib_parquet,
        config=cfg,
        artefact_dir=args.artefact_dir,
        chunk_size=args.chunk_size,
    )

    if isinstance(result, tuple):
        print(f"ABSTAINED: {result[2]}")
        sys.exit(0)

    print(f"CERTIFIED: Λ̂={result.lambda_hat_mask.sum()} points  θ̂={result.theta_hat.tolist()}")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the CLI**

```bash
cd systematic-review-system
python -m cascade_rc.calibration.main_calibrate --help
```

Expected: prints usage with `--topic`, `--calib-parquet`, `--artefact-dir`, `--chunk-size`.

- [ ] **Step 3: Run all tests to confirm nothing is broken**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/ -v --tb=short
```

Expected: all tests pass (no regressions).

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/calibration/main_calibrate.py
git commit -m "feat(main_calibrate): add CLI entry point (python -m cascade_rc.calibration.main_calibrate)"
```

---

## Self-Review Against Spec

| Spec requirement | Task |
|---|---|
| Algorithm 1 steps 1–10 | Tasks 4–5 |
| Abstain when m₊ < N_min, return 3-tuple | Task 4 |
| η_i = L̃_i − L_i (corrected slack, not proxy=0) | Task 2 + Task 5 |
| η̂⁻⋆ via wsr_lcb with Bonferroni delta_eta/G | Task 5 |
| α†(θ) = α + η̂⁻⋆ (addition) | Task 5 |
| p_HB via hb_pvalues | Task 5 |
| Fixed-sequence walk (no inner Bonferroni) | Task 5 |
| θ̂ = argmin expected_cost over Λ̂ | Task 5 |
| c_human=5.0, c_llm=0.001 in LTTBudget | Task 1 |
| Persist pkl + JSON; partial.pkl | Task 3 + Task 5 |
| Checkpoint every 500 grid evaluations | Task 5 (`_compute_eta_lcb_chunked`) |
| Resume from partial on startup | Task 5 |
| test_certification_synthetic — non-empty Λ̂, pinned θ̂ | Tasks 5–6 |
| test_abstention_when_m_plus_below_N_min | Task 4 |
| test_resume_from_partial — bytes-identical | Task 6 |
| CLI `python -m cascade_rc.calibration.main_calibrate` | Task 7 |
