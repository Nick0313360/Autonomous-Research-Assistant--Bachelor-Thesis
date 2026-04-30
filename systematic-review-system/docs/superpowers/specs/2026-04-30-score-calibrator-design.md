# Design: Prompt 2.1 — Isotonic/Platt Calibrator Bundle

**Date:** 2026-04-30  
**Branch:** feature_redesignv2  
**Files touched:** `cascade_rc/data/score_normalizer.py`, `tier2_screening/hybrid_retriever.py`, `orchestrators/screening_orchestrator.py`, `cascade_rc/tests/test_score_normalizer.py`

---

## Goal

Fit two calibrators (isotonic regression + Platt/LR) on each topic's RRF scores, pick the lower-NLL one, persist it as a `joblib` bundle, and inject it into `HybridRetriever` so every ranked candidate receives a calibrated `calibrated_score ∈ [0, 1]` alongside its raw RRF score.

---

## Architecture

```
score_normalizer.py  (CLI / offline)
  ├─ fit IsotonicRegression(out_of_bounds='clip') on 80 % of calib split
  ├─ fit LogisticRegression(C=1e10, solver='lbfgs') on 80 % of calib split   ← Platt
  ├─ evaluate Brier + NLL on held-out 20 %
  ├─ pick lower-NLL winner; record both metrics in metadata
  ├─ joblib.dump({"chosen", "isotonic", "platt", "metadata"}, artefacts/cascade_rc/calibrators/<topic>.pkl)
  └─ reliability diagram (10 bins) → artefacts/cascade_rc/calibrators/<topic>.png

hybrid_retriever.py  (inference)
  ├─ HybridRetriever(calibrator_path: Path | None = None)
  │     loads bundle → wraps in CalibratorBundle once at construction
  ├─ filter(ranked) batch-calls CalibratorBundle.predict(rrf_scores_array)
  │     → stores float in RankedCandidate.calibrated_score
  └─ logs one INFO line: chosen family + NLL on construction

screening_orchestrator.py
  └─ __init__ gains calibrator_path: Path | None = None
        → forwarded to HybridRetriever(calibrator_path=calibrator_path)
```

---

## Components

### 1. `CalibratorBundle` (new class, `score_normalizer.py`)

Runtime wrapper around the loaded `dict`. Created once at `HybridRetriever` construction.

```python
class CalibratorBundle:
    def __init__(self, bundle: dict) -> None: ...
    def predict(self, s: np.ndarray) -> np.ndarray:
        # isotonic: iso.predict(s)          → shape (n,)
        # platt:    lr.predict_proba(s.reshape(-1,1))[:,1]  → shape (n,)
        # always returns float64 array, shape (n,), values clipped to [0, 1]
    @property
    def chosen(self) -> str: ...   # "isotonic" | "platt"
    @property
    def nll(self) -> float: ...    # NLL of chosen calibrator on held-out 20 %
    metadata: dict                 # full metadata dict (Brier, NLL, sample sizes, timestamp)
```

Also expose two public helpers:

```python
def load_calibrator(path: Path) -> CalibratorBundle: ...
def save_calibrator(bundle_dict: dict, path: Path) -> None: ...
```

### 2. Updated `score_normalizer.main()`

1. Load parquet for the topic; compute raw RRF scores via `compute_raw_scores()`.
2. Stratified 80/20 split (same `StratifiedShuffleSplit` pattern already in use).
3. Fit `IsotonicRegression(out_of_bounds='clip')` on the 80 % train fold.
4. Fit `LogisticRegression(C=1e10, solver='lbfgs', max_iter=1000, random_state=42)` on the 80 % train fold.
5. On held-out 20 %: compute `brier_score_loss` and `log_loss` for each.
6. `chosen = "isotonic" if nll_iso < nll_platt else "platt"`.
7. Persist bundle: `joblib.dump({"chosen", "isotonic", "platt", "metadata"}, out_pkl)`.
8. Reliability diagram using `_reliability_plot()` (10 bins) to `.png`.

Existing `fit_platt()` / `apply_platt()` functions are **not changed** — old tests continue to pass.

### 3. `RankedCandidate` (updated dataclass)

Adds one optional field:

```python
calibrated_score: Optional[float] = None
```

`rrf_score` is unchanged. Downstream code that ignores `calibrated_score` is unaffected.

### 4. `HybridRetriever` (updated)

- Constructor: `__init__(self, calibrator_path: Path | None = None)`.
- On init: if `calibrator_path` is set and the file exists, load it into `self._calibrator: Optional[CalibratorBundle]`.
- Logs **one** `INFO` line at construction time: `"Loaded %s calibrator (NLL=%.4f) from %s"`.
- In `filter()`: if `self._calibrator` is set, batch-predict across all `ranked` candidates and assign `rc.calibrated_score = float(calibrated[i])`.

### 5. `ScreeningOrchestrator` (minimal change)

```python
def __init__(self, ..., calibrator_path: Path | None = None) -> None:
    ...
    self._hybrid_retriever = HybridRetriever(calibrator_path=calibrator_path)
```

---

## Artefact layout

```
artefacts/cascade_rc/calibrators/
  CD008874.pkl
  CD008874.png
  CD012080.pkl
  CD012080.png
  ...
```

---

## Tests (`cascade_rc/tests/test_score_normalizer.py`)

### `test_calibrator_monotone`
For both isotonic and platt calibrators (fitted on synthetic RRF-range data), apply `.predict()` on a linearly-spaced grid; assert `np.all(np.diff(predictions) >= -1e-10)`.

### `test_calibrator_brier_lower_than_uncalibrated`
Brier score of the chosen calibrator on the held-out 20 % must be strictly less than the Brier score of the identity map (raw RRF clipped to [0, 1]).

### `test_persisted_pkl_roundtrip`
`save_calibrator(bundle_dict, tmp_path / "test.pkl")` → `load_calibrator(tmp_path / "test.pkl")` → `bundle.predict(grid)` matches in-memory predictions exactly (np.allclose).

---

## Invariants

- `calibrated_score ∈ [0, 1]` — enforced by `np.clip` inside `CalibratorBundle.predict()`.
- Backwards compatible: `calibrator_path=None` leaves all existing behaviour unchanged.
- `fit_platt()` / `apply_platt()` untouched — existing `tests/test_score_normalizer.py` passes without modification.
- Private sklearn API avoided: Platt uses `LogisticRegression(C=1e10)` (same sigmoid, public API).

---

## Open decisions (resolved)

| # | Question | Decision |
|---|----------|----------|
| 1 | `cand.score` field name | Add `calibrated_score: Optional[float] = None` to `RankedCandidate`; keep `rrf_score` untouched |
| 2 | Platt implementation | `LogisticRegression(C=1e10, solver='lbfgs')` — no private sklearn API |
| 3 | Orchestrator wiring | `calibrator_path: Path \| None = None` added directly to `ScreeningOrchestrator.__init__`; caller computes path |
