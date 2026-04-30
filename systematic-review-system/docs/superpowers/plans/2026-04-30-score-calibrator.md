# Score Calibrator Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fit per-topic isotonic and Platt calibrators on RRF scores, persist the lower-NLL one as a joblib bundle, and inject it into `HybridRetriever.filter()` so every ranked candidate receives `calibrated_score ∈ [0, 1]`.

**Architecture:** A new `CalibratorBundle` class in `score_normalizer.py` wraps the loaded dict and exposes a unified `.predict(s)` → `(n,)` float64 array. `HybridRetriever` receives an optional `calibrator_path` at construction, loads the bundle once, and batch-applies it inside `filter()`. `ScreeningOrchestrator` forwards the path through unchanged.

**Tech Stack:** Python 3.11, scikit-learn (`IsotonicRegression`, `LogisticRegression`), joblib, numpy, matplotlib (Agg backend), pytest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `cascade_rc/tests/test_score_normalizer.py` | 4 new calibrator tests |
| Modify | `cascade_rc/data/score_normalizer.py` | `CalibratorBundle`, `fit_calibrators`, `save_calibrator`, `load_calibrator`, updated `main()` |
| Modify | `tier2_screening/hybrid_retriever.py` | `RankedCandidate.calibrated_score`, `HybridRetriever(calibrator_path)`, calibration in `filter()` |
| Modify | `orchestrators/screening_orchestrator.py` | `calibrator_path` passthrough to `HybridRetriever` |

---

## Task 1: Write all four failing tests

**Files:**
- Create: `cascade_rc/tests/test_score_normalizer.py`

- [ ] **Step 1.1: Create the test file with all four tests**

```python
"""cascade_rc/tests/test_score_normalizer.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_calibrators(seed: int = 0):
    """Return (iso, platt) fitted on synthetic RRF-range data."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.016, 0.033, 200)
    y = (x + rng.uniform(0.0, 0.004, 200) > np.median(x)).astype(int)
    iso = IsotonicRegression(out_of_bounds="clip").fit(x, y)
    platt = LogisticRegression(
        C=1e10, solver="lbfgs", max_iter=1000, random_state=42
    ).fit(x.reshape(-1, 1), y)
    return iso, platt, x, y


# ---------------------------------------------------------------------------
# test_calibrator_monotone
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chosen", ["isotonic", "platt"])
def test_calibrator_monotone(chosen: str) -> None:
    """Both calibrators produce non-decreasing predictions on a sorted grid."""
    from cascade_rc.data.score_normalizer import CalibratorBundle

    iso, platt, _, _ = _make_calibrators(seed=0)
    bundle = CalibratorBundle(
        {"chosen": chosen, "isotonic": iso, "platt": platt, "metadata": {}}
    )
    grid = np.linspace(0.016, 0.033, 200)
    preds = bundle.predict(grid)
    diffs = np.diff(preds)
    assert np.all(diffs >= -1e-10), (
        f"{chosen}: not monotone; min diff = {diffs.min():.2e}"
    )


# ---------------------------------------------------------------------------
# test_calibrator_brier_lower_than_uncalibrated
# ---------------------------------------------------------------------------

def test_calibrator_brier_lower_than_uncalibrated() -> None:
    """Chosen calibrator Brier score beats the identity map on the val set."""
    from cascade_rc.data.score_normalizer import CalibratorBundle

    rng = np.random.default_rng(42)
    x = rng.uniform(0.016, 0.033, 300)
    y = (x + rng.uniform(0.0, 0.004, 300) > np.median(x)).astype(int)

    n_train = 240
    x_train, y_train = x[:n_train], y[:n_train]
    x_val, y_val = x[n_train:], y[n_train:]

    iso = IsotonicRegression(out_of_bounds="clip").fit(x_train, y_train)
    platt = LogisticRegression(
        C=1e10, solver="lbfgs", max_iter=1000, random_state=42
    ).fit(x_train.reshape(-1, 1), y_train)

    p_iso = iso.predict(x_val)
    p_platt = platt.predict_proba(x_val.reshape(-1, 1))[:, 1]
    chosen = "isotonic" if log_loss(y_val, p_iso) <= log_loss(y_val, p_platt) else "platt"

    bundle = CalibratorBundle(
        {"chosen": chosen, "isotonic": iso, "platt": platt, "metadata": {}}
    )
    p_cal = bundle.predict(x_val)
    p_raw = np.clip(x_val, 0.0, 1.0)  # identity map: RRF scores ≈ 0.016–0.033

    assert brier_score_loss(y_val, p_cal) < brier_score_loss(y_val, p_raw), (
        f"Calibrator Brier {brier_score_loss(y_val, p_cal):.4f} >= "
        f"identity Brier {brier_score_loss(y_val, p_raw):.4f}"
    )


# ---------------------------------------------------------------------------
# test_persisted_pkl_roundtrip
# ---------------------------------------------------------------------------

def test_persisted_pkl_roundtrip(tmp_path: Path) -> None:
    """Predictions from a loaded .pkl match in-memory predictions exactly."""
    from cascade_rc.data.score_normalizer import (
        CalibratorBundle,
        load_calibrator,
        save_calibrator,
    )

    iso, platt, _, _ = _make_calibrators(seed=7)
    bundle_dict = {
        "chosen": "isotonic",
        "isotonic": iso,
        "platt": platt,
        "metadata": {"nll_isotonic": 0.5, "nll_platt": 0.6},
    }
    pkl_path = tmp_path / "test.pkl"
    save_calibrator(bundle_dict, pkl_path)
    loaded = load_calibrator(pkl_path)

    grid = np.linspace(0.016, 0.033, 50)
    in_memory = CalibratorBundle(bundle_dict).predict(grid)
    from_disk = loaded.predict(grid)

    assert np.allclose(in_memory, from_disk), "Predictions differ after pkl roundtrip"


# ---------------------------------------------------------------------------
# test_calibrator_predict_empty_input
# ---------------------------------------------------------------------------

def test_calibrator_predict_empty_input() -> None:
    """predict(np.array([])) returns a zero-length array without raising."""
    from cascade_rc.data.score_normalizer import CalibratorBundle

    iso, platt, _, _ = _make_calibrators(seed=1)
    bundle = CalibratorBundle(
        {"chosen": "isotonic", "isotonic": iso, "platt": platt, "metadata": {}}
    )
    result = bundle.predict(np.array([]))
    assert len(result) == 0
```

- [ ] **Step 1.2: Run tests — expect ImportError (CalibratorBundle not yet defined)**

```bash
cd systematic-review-system
venv/bin/pytest cascade_rc/tests/test_score_normalizer.py -v 2>&1 | head -30
```

Expected: 4 errors, all `ImportError: cannot import name 'CalibratorBundle'`

- [ ] **Step 1.3: Commit the failing tests**

```bash
git add cascade_rc/tests/test_score_normalizer.py
git commit -m "test(cascade_rc): add failing calibrator bundle tests (TDD)"
```

---

## Task 2: Implement `CalibratorBundle`, `save_calibrator`, `load_calibrator`

**Files:**
- Modify: `cascade_rc/data/score_normalizer.py` (after the `PlattCalibrator` type alias, around line 36)

- [ ] **Step 2.1: Add imports and the three new symbols to `score_normalizer.py`**

Open `cascade_rc/data/score_normalizer.py`. After the existing imports block (after `from models.data_classes import CandidateRecord`), add:

```python
import joblib
```

After the `_RRF_K = 60` line, add the following block (before `compute_raw_scores`):

```python
# ---------------------------------------------------------------------------
# CalibratorBundle — unified predict() wrapper around the persisted dict
# ---------------------------------------------------------------------------

class CalibratorBundle:
    """
    Runtime wrapper around a joblib-persisted calibrator dict.

    The dict format is:
        {"chosen": "isotonic" | "platt",
         "isotonic": IsotonicRegression,
         "platt": LogisticRegression,
         "metadata": {...}}
    """

    def __init__(self, bundle: dict) -> None:
        self._chosen: str = bundle["chosen"]
        self._iso = bundle["isotonic"]
        self._platt = bundle["platt"]
        self.metadata: dict = bundle.get("metadata", {})

    def predict(self, s: np.ndarray) -> np.ndarray:
        """
        Return calibrated probabilities for raw RRF scores *s*.

        Always returns shape (n,) float64, values clipped to [0, 1].
        Returns np.array([]) for empty input without raising.
        """
        s = np.asarray(s, dtype=np.float64)
        if s.size == 0:
            return np.array([], dtype=np.float64)
        if self._chosen == "isotonic":
            out = self._iso.predict(s)
        else:
            out = self._platt.predict_proba(s.reshape(-1, 1))[:, 1]
        return np.clip(out, 0.0, 1.0).astype(np.float64)

    @property
    def chosen(self) -> str:
        return self._chosen

    @property
    def nll(self) -> float:
        return float(self.metadata.get(f"nll_{self._chosen}", float("nan")))


def save_calibrator(bundle_dict: dict, path: Path) -> None:
    """Persist a calibrator bundle dict to *path* using joblib."""
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle_dict, path)
    logger.info("Saved calibrator bundle → %s", path)


def load_calibrator(path: Path) -> CalibratorBundle:
    """Load a joblib-persisted bundle and return a CalibratorBundle."""
    return CalibratorBundle(joblib.load(path))
```

- [ ] **Step 2.2: Run tests — roundtrip and empty-input should now pass; monotone/brier still need `fit_calibrators`**

```bash
venv/bin/pytest cascade_rc/tests/test_score_normalizer.py -v 2>&1 | tail -20
```

Expected: `test_persisted_pkl_roundtrip` PASSED, `test_calibrator_predict_empty_input` PASSED, the other two FAILED with `ImportError: cannot import name 'fit_calibrators'` or similar.

- [ ] **Step 2.3: Commit**

```bash
git add cascade_rc/data/score_normalizer.py
git commit -m "feat(cascade_rc): add CalibratorBundle, save_calibrator, load_calibrator"
```

---

## Task 3: Implement `fit_calibrators` helper

**Files:**
- Modify: `cascade_rc/data/score_normalizer.py` (add after `load_calibrator`, before `compute_raw_scores`)

- [ ] **Step 3.1: Add `fit_calibrators` to `score_normalizer.py`**

Insert the following block immediately after `load_calibrator`:

```python
def fit_calibrators(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
) -> dict:
    """Fit iso + Platt on train fold; pick lower-NLL on val fold; return bundle dict."""
    import datetime
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss, log_loss

    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(x_train, y_train)

    platt = LogisticRegression(
        C=1e10, solver="lbfgs", max_iter=1000, random_state=42
    )
    platt.fit(x_train.reshape(-1, 1), y_train)

    # Clip isotonic predictions away from 0/1 to avoid infinite log-loss
    p_iso = np.clip(iso.predict(x_val), 1e-15, 1.0 - 1e-15)
    p_platt = platt.predict_proba(x_val.reshape(-1, 1))[:, 1]

    nll_iso = float(log_loss(y_val, p_iso))
    nll_platt = float(log_loss(y_val, p_platt))
    brier_iso = float(brier_score_loss(y_val, p_iso))
    brier_platt = float(brier_score_loss(y_val, p_platt))

    chosen = "isotonic" if nll_iso <= nll_platt else "platt"
    logger.info(
        "fit_calibrators: chosen=%s  NLL iso=%.4f platt=%.4f  "
        "Brier iso=%.4f platt=%.4f",
        chosen, nll_iso, nll_platt, brier_iso, brier_platt,
    )

    return {
        "chosen": chosen,
        "isotonic": iso,
        "platt": platt,
        "metadata": {
            "nll_isotonic": nll_iso,
            "nll_platt": nll_platt,
            "brier_isotonic": brier_iso,
            "brier_platt": brier_platt,
            "n_train": int(len(x_train)),
            "n_val": int(len(x_val)),
            "timestamp": datetime.datetime.utcnow().isoformat(),
        },
    }
```

- [ ] **Step 3.2: Run all four tests — all should pass**

```bash
venv/bin/pytest cascade_rc/tests/test_score_normalizer.py -v
```

Expected output:
```
PASSED cascade_rc/tests/test_score_normalizer.py::test_calibrator_monotone[isotonic]
PASSED cascade_rc/tests/test_score_normalizer.py::test_calibrator_monotone[platt]
PASSED cascade_rc/tests/test_score_normalizer.py::test_calibrator_brier_lower_than_uncalibrated
PASSED cascade_rc/tests/test_score_normalizer.py::test_persisted_pkl_roundtrip
PASSED cascade_rc/tests/test_score_normalizer.py::test_calibrator_predict_empty_input
5 passed
```

- [ ] **Step 3.3: Also run the pre-existing score_normalizer tests to confirm no regression**

```bash
venv/bin/pytest tests/test_score_normalizer.py -v
```

Expected: all existing tests still PASSED (fit_platt / apply_platt unchanged).

- [ ] **Step 3.4: Commit**

```bash
git add cascade_rc/data/score_normalizer.py
git commit -m "feat(cascade_rc): add fit_calibrators — isotonic + Platt, NLL model selection"
```

---

## Task 4: Update `score_normalizer.main()` to emit calibrator bundle + diagram

**Files:**
- Modify: `cascade_rc/data/score_normalizer.py` — the `main()` function

- [ ] **Step 4.1: Replace the Platt-only `main()` body with the bundle-aware version**

Find the existing `main()` function (starts at line ~185). Replace the entire body of `main()` (everything from `import argparse` to `print(f"Platt calibrator → {platt_pkl}")`) with:

```python
def main() -> None:
    import argparse
    import sys

    from sklearn.model_selection import StratifiedShuffleSplit

    _repo_root = Path(__file__).parent.parent.parent.resolve()
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

    from cascade_rc.data.clef_tar_loader import load_topic

    parser = argparse.ArgumentParser(
        description="Fit calibration bundle on CLEF-TAR topic Tier-2 scores."
    )
    parser.add_argument(
        "--topic",
        required=True,
        choices=["CD008874", "CD012080", "CD012768"],
        help="CLEF-TAR 2019 DTA topic ID.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Root data directory (default: <repo>/data).",
    )
    parser.add_argument(
        "--artefact-dir",
        type=Path,
        default=None,
        help="Artefact output root (default: <repo>/artefacts/cascade_rc).",
    )
    args = parser.parse_args()

    topic_id: str = args.topic
    data_dir: Path = args.data_dir or (_repo_root / "data")
    artefact_dir: Path = args.artefact_dir or (_repo_root / "artefacts" / "cascade_rc")
    clef_dir: Path = data_dir / "clef_tar"
    cal_dir: Path = artefact_dir / "calibrators"

    parquet_path = clef_dir / f"{topic_id}.parquet"
    if not parquet_path.exists():
        sys.exit(
            f"ERROR: {parquet_path} not found.\n"
            "Run: python -m cascade_rc.data.clef_tar_loader "
            f"--topic {topic_id} --out {clef_dir}"
        )

    try:
        topic = load_topic(topic_id, data_dir)
        query = f"{topic.title} {topic.boolean_query}"
    except Exception as exc:
        logger.warning(
            "Could not load topic metadata (%s); using topic_id as query.", exc
        )
        query = topic_id

    logger.info("Computing raw scores for %s …", topic_id)
    scored_df = compute_raw_scores(parquet_path, query)

    raw_scores = scored_df["raw_score"].to_numpy()
    y = scored_df["y_abstract"].to_numpy().astype(int)

    # Stratified 80 % train / 20 % val split within the calibration split
    sss = StratifiedShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, val_idx = next(sss.split(raw_scores, y))

    bundle_dict = fit_calibrators(
        x_train=raw_scores[train_idx],
        y_train=y[train_idx],
        x_val=raw_scores[val_idx],
        y_val=y[val_idx],
    )

    # ---- Persist bundle ----------------------------------------------------
    cal_dir.mkdir(parents=True, exist_ok=True)
    pkl_path = cal_dir / f"{topic_id}.pkl"
    save_calibrator(bundle_dict, pkl_path)

    # ---- Reliability diagram -----------------------------------------------
    bundle = CalibratorBundle(bundle_dict)
    s_val = bundle.predict(raw_scores[val_idx])
    png_path = cal_dir / f"{topic_id}.png"
    _reliability_plot(s_val, y[val_idx], n_bins=10, out_path=png_path, topic_id=topic_id)

    # ---- Console summary ---------------------------------------------------
    meta = bundle_dict["metadata"]
    print(f"Topic           : {topic_id}")
    print(f"Chosen          : {bundle_dict['chosen']}")
    print(f"NLL isotonic    : {meta['nll_isotonic']:.4f}")
    print(f"NLL platt       : {meta['nll_platt']:.4f}")
    print(f"Brier isotonic  : {meta['brier_isotonic']:.4f}")
    print(f"Brier platt     : {meta['brier_platt']:.4f}")
    print(f"Calibrator pkl  → {pkl_path}")
    print(f"Reliability plot→ {png_path}")
```

- [ ] **Step 4.2: Verify the file still imports cleanly**

```bash
venv/bin/python -c "import cascade_rc.data.score_normalizer; print('OK')"
```

Expected: `OK`

- [ ] **Step 4.3: Re-run all cascade_rc calibrator tests to confirm no breakage**

```bash
venv/bin/pytest cascade_rc/tests/test_score_normalizer.py tests/test_score_normalizer.py -v
```

Expected: all 5 new tests + all pre-existing score_normalizer tests pass.

- [ ] **Step 4.4: Commit**

```bash
git add cascade_rc/data/score_normalizer.py
git commit -m "feat(cascade_rc): update score_normalizer.main() to emit calibrator bundle + diagram"
```

---

## Task 5: Add `calibrated_score` to `RankedCandidate`

**Files:**
- Modify: `tier2_screening/hybrid_retriever.py` — `RankedCandidate` dataclass (line ~66)

- [ ] **Step 5.1: Add the optional field to `RankedCandidate`**

In `tier2_screening/hybrid_retriever.py`, find the `RankedCandidate` dataclass:

```python
@dataclass
class RankedCandidate:
    candidate:   CandidateRecord
    bm25_rank:   int      # 1 = best BM25 match
    dense_rank:  int      # 1 = best dense match
    rrf_score:   float    # higher = more relevant
```

Replace it with:

```python
@dataclass
class RankedCandidate:
    candidate:        CandidateRecord
    bm25_rank:        int            # 1 = best BM25 match
    dense_rank:       int            # 1 = best dense match
    rrf_score:        float          # higher = more relevant
    calibrated_score: Optional[float] = None  # set by HybridRetriever when calibrator loaded
```

Also add `Optional` to the existing import at the top of the file — the current import is:

```python
from typing import Dict, List, Optional, Tuple
```

`Optional` is already imported, so no change needed.

- [ ] **Step 5.2: Verify the dataclass instantiates cleanly**

```bash
venv/bin/python -c "
from tier2_screening.hybrid_retriever import RankedCandidate
from unittest.mock import MagicMock
rc = RankedCandidate(candidate=MagicMock(), bm25_rank=1, dense_rank=1, rrf_score=0.03)
print('calibrated_score default:', rc.calibrated_score)
assert rc.calibrated_score is None
print('OK')
"
```

Expected: `calibrated_score default: None` then `OK`.

- [ ] **Step 5.3: Commit**

```bash
git add tier2_screening/hybrid_retriever.py
git commit -m "feat(tier2): add calibrated_score field to RankedCandidate"
```

---

## Task 6: Update `HybridRetriever` to load and apply the calibrator

**Files:**
- Modify: `tier2_screening/hybrid_retriever.py`

- [ ] **Step 6.1: Update `HybridRetriever.__init__` to accept and load `calibrator_path`**

Find the `__init__` method of `HybridRetriever` (around line 90):

```python
def __init__(self) -> None:
    self._faiss_index:   Optional[faiss.IndexFlatIP] = None
    self._bm25:          Optional[BM25Okapi] = None
    self._id_map:        Dict[int, str] = {}
    self._record_map:    Dict[str, CandidateRecord] = {}
    self._embed_dim:     int = 128
```

Replace with:

```python
def __init__(self, calibrator_path: Optional[Path] = None) -> None:
    self._faiss_index:   Optional[faiss.IndexFlatIP] = None
    self._bm25:          Optional[BM25Okapi] = None
    self._id_map:        Dict[int, str] = {}
    self._record_map:    Dict[str, CandidateRecord] = {}
    self._embed_dim:     int = 128
    self._calibrator:    Optional[Any] = None

    if calibrator_path is not None:
        try:
            from cascade_rc.data.score_normalizer import load_calibrator
            self._calibrator = load_calibrator(calibrator_path)
            logger.info(
                "Loaded %s calibrator (NLL=%.4f) from %s",
                self._calibrator.chosen,
                self._calibrator.nll,
                calibrator_path,
            )
        except Exception as exc:
            logger.warning(
                "Could not load calibrator from %s: %s — running uncalibrated",
                calibrator_path,
                exc,
            )
```

Also add `Path` and `Any` to the imports at the top of `hybrid_retriever.py`. The current typing import is:

```python
from typing import Dict, List, Optional, Tuple
```

Change it to:

```python
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
```

- [ ] **Step 6.2: Update `filter()` to batch-apply calibration**

Find the `filter` method in `HybridRetriever` (around line 230). Replace the entire `filter` body with:

```python
def filter(
    self,
    ranked:    List[RankedCandidate],
    threshold: float = 0.01,
) -> Tuple[List[RankedCandidate], List[RankedCandidate]]:
    """Split ranked candidates at *threshold*; batch-apply calibrator if loaded."""
    if self._calibrator is not None and ranked:
        rrf_arr = np.array([rc.rrf_score for rc in ranked], dtype=np.float64)
        calibrated = self._calibrator.predict(rrf_arr)
        for rc, cal in zip(ranked, calibrated):
            rc.calibrated_score = float(cal)

    above = [r for r in ranked if r.rrf_score >= threshold]
    below = [r for r in ranked if r.rrf_score <  threshold]
    logger.info(
        "filter(threshold=%.4f): %d above, %d below",
        threshold, len(above), len(below),
    )
    return above, below
```

- [ ] **Step 6.3: Verify HybridRetriever still initialises cleanly without a path**

```bash
venv/bin/python -c "
from tier2_screening.hybrid_retriever import HybridRetriever
r = HybridRetriever()
print('_calibrator:', r._calibrator)
assert r._calibrator is None
print('OK — no calibrator loaded')
"
```

Expected: `_calibrator: None` then `OK — no calibrator loaded`.

- [ ] **Step 6.4: Verify calibrator is applied in filter() when loaded**

```bash
venv/bin/python -c "
import numpy as np
from unittest.mock import MagicMock
from tier2_screening.hybrid_retriever import HybridRetriever, RankedCandidate

# Build a tiny pkl in /tmp
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
import joblib, tempfile, pathlib

x = np.array([0.016, 0.020, 0.025, 0.030, 0.033])
y = np.array([0, 0, 1, 1, 1])
iso = IsotonicRegression(out_of_bounds='clip').fit(x, y)
platt = LogisticRegression(C=1e10, solver='lbfgs', max_iter=1000, random_state=42).fit(x.reshape(-1,1), y)
tmp = pathlib.Path(tempfile.mkdtemp()) / 'test.pkl'
joblib.dump({'chosen': 'isotonic', 'isotonic': iso, 'platt': platt, 'metadata': {'nll_isotonic': 0.5, 'nll_platt': 0.6}}, tmp)

r = HybridRetriever(calibrator_path=tmp)
ranked = [
    RankedCandidate(candidate=MagicMock(), bm25_rank=1, dense_rank=1, rrf_score=0.020),
    RankedCandidate(candidate=MagicMock(), bm25_rank=2, dense_rank=2, rrf_score=0.033),
]
above, below = r.filter(ranked)
for rc in ranked:
    assert rc.calibrated_score is not None
    assert 0.0 <= rc.calibrated_score <= 1.0
print('calibrated_scores:', [rc.calibrated_score for rc in ranked])
print('OK')
"
```

Expected: two float values in [0,1], then `OK`.

- [ ] **Step 6.5: Commit**

```bash
git add tier2_screening/hybrid_retriever.py
git commit -m "feat(tier2): inject CalibratorBundle into HybridRetriever; apply in filter()"
```

---

## Task 7: Update `ScreeningOrchestrator` to forward `calibrator_path`

**Files:**
- Modify: `orchestrators/screening_orchestrator.py`

- [ ] **Step 7.1: Add `calibrator_path` parameter and forward it**

Find `ScreeningOrchestrator.__init__` (around line 74). The current signature is:

```python
def __init__(
    self,
    encoder:    Any,
    llm_client: Any,
    review_id:  str,
    prisma:     Optional[PRISMAManager] = None,
) -> None:
```

Replace with:

```python
def __init__(
    self,
    encoder:         Any,
    llm_client:      Any,
    review_id:       str,
    prisma:          Optional[PRISMAManager] = None,
    calibrator_path: Optional[Path] = None,
) -> None:
```

Then find the line:

```python
self._hybrid_retriever = HybridRetriever()
```

Replace it with:

```python
self._hybrid_retriever = HybridRetriever(calibrator_path=calibrator_path)
```

Add `Path` to the imports at the top of `screening_orchestrator.py`. Find:

```python
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
```

Change to:

```python
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
```

- [ ] **Step 7.2: Verify ScreeningOrchestrator instantiates cleanly**

```bash
venv/bin/python -c "
from unittest.mock import MagicMock
from orchestrators.screening_orchestrator import ScreeningOrchestrator
so = ScreeningOrchestrator(encoder=MagicMock(), llm_client=MagicMock(), review_id='test')
print('calibrator on retriever:', so._hybrid_retriever._calibrator)
assert so._hybrid_retriever._calibrator is None
print('OK')
"
```

Expected: `calibrator on retriever: None` then `OK`.

- [ ] **Step 7.3: Commit**

```bash
git add orchestrators/screening_orchestrator.py
git commit -m "feat(orchestrators): forward calibrator_path to HybridRetriever"
```

---

## Task 8: Full test suite — verify no regressions

- [ ] **Step 8.1: Run the full test suite**

```bash
venv/bin/pytest cascade_rc/tests/ tests/ -v --tb=short 2>&1 | tail -40
```

Expected: all tests pass. The new tests in `cascade_rc/tests/test_score_normalizer.py` should show 5 PASSED. The pre-existing `tests/test_score_normalizer.py` should still pass (unchanged `fit_platt`/`apply_platt`).

- [ ] **Step 8.2: If any test fails, read the traceback and fix**

For import errors: check that `from pathlib import Path` and `from typing import Any` are added wherever needed.

For shape errors: verify `CalibratorBundle.predict()` returns `(n,)` not `(n,1)` — the `predict_proba(X.reshape(-1,1))[:,1]` slice should be 1-D; if not, add `.ravel()`.

- [ ] **Step 8.3: Final commit**

```bash
git add -p  # stage any remaining fixes
git commit -m "test(cascade_rc): all calibrator tests passing; no regressions"
```

---

## Acceptance Checklist

- [ ] `cascade_rc/tests/test_score_normalizer.py` — 5 tests, all PASSED
- [ ] `tests/test_score_normalizer.py` — existing tests still PASSED
- [ ] `RankedCandidate.calibrated_score` exists, defaults to `None`
- [ ] `HybridRetriever(calibrator_path=None)` — no calibrator, no INFO log
- [ ] `HybridRetriever(calibrator_path=<path>)` — INFO log fires once at construction
- [ ] After `filter()`, all `RankedCandidate.calibrated_score` values are `∈ [0, 1]` when calibrator loaded
- [ ] `ScreeningOrchestrator.__init__` accepts and forwards `calibrator_path`
- [ ] `score_normalizer.main()` writes `.pkl` + `.png` to `artefacts/cascade_rc/calibrators/`
