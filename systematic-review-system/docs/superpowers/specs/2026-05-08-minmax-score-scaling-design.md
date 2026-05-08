# Design: Pre-Calibration Rank-Preserving Min-Max Score Scaling

**Date:** 2026-05-08
**Status:** Approved
**Author:** NickGolovanov + Claude Code

---

## Problem

For some CLEF-TAR DTA topics (e.g. CD012768), the Tier-1 base scores in the `s` column are
heavily squashed into a microscopic range (e.g. `[0.0110, 0.0320]`). Because the LTT walk grid
is anchored on quantiles of `s`, the spatial resolution within this tiny interval is insufficient
to place a safe separating threshold `λ_lo > 0`. The walker conservatively defaults to
`λ_lo = 0.0`, collapsing the cascade: zero documents are cheap-rejected, 100% of workload is
escalated, and WSS@95 flatlines at −0.05.

---

## Solution

Apply a **global, rank-preserving Min-Max affine scaling** to the `s` column immediately after
loading each topic's parquet and **before** any split-based operations. This stretches the
squashed cluster to the full `[0, 1]` parameter space, giving the grid sufficient resolution to
find a safe `λ_lo > 0`.

Conformal Prediction relies on **rank-order**, not absolute score magnitudes. An affine
transformation preserves rank order, so the exchangeability guarantee of Theorem 5 is
unaffected.

---

## Invariants

1. **Global scaling only.** Min and max are computed from the **entire topic dataframe** (all
   splits: is_split ∈ {0, 1, 2}) in a single pass. Per-split scaling would produce different
   coordinate systems for `θ̂` and the WSS evaluation, violating the exchangeability assumption.

2. **Thresholds and test data must share a coordinate system.** `θ̂[0]` (`λ_lo`) is learned on
   the scaled calibration space. The WSS evaluation (`s < λ_lo`) must also use the same scaled
   `s` values. This requires two injection sites (see below).

3. **Idempotent.** Calling the scaler on already-scaled `[0, 1]` data is a no-op (s_min=0,
   s_max=1 → identity transform).

4. **Ablation-safe.** The flag defaults to `False`, preserving current behavior exactly. Ablation
   study: run with `normalize_base_scores=False` to produce unscaled baseline, then `=True` to
   produce the scaled results.

---

## Changes

### 1. `cascade_rc/config.py` — `CascadeRCConfig`

Add one field:

```python
normalize_base_scores: bool = False
```

- Default `False` — no existing test or run breaks.
- Configurable via env var `CRC_NORMALIZE_BASE_SCORES=true`.
- Appears in `config_snapshot` persisted in `CertificationResult` for audit trail.

### 2. `cascade_rc/data/score_normalizer.py` — new public function

```python
def minmax_scale_s(df: pd.DataFrame) -> pd.DataFrame:
    """Rank-preserving min-max scale the 's' column to [0, 1].

    Computed globally (all rows) so calibration and test splits stay in the
    same coordinate system. No-op when all scores are identical.
    """
    s_min = df["s"].min()
    s_max = df["s"].max()
    if s_max > s_min:
        df = df.copy()
        df["s"] = (df["s"] - s_min) / (s_max - s_min)
    return df
```

Returns a copy only when a transformation is applied; returns the input unchanged otherwise.

### 3. Injection Site 1 — `cascade_rc/calibration/main_calibrate.py::calibrate()`

**Location:** immediately after `df = pd.read_parquet(calib_parquet)` (currently line 166),
before any split filtering, debug prints, or numpy array extraction.

```python
df = pd.read_parquet(calib_parquet)
if config.normalize_base_scores:
    from cascade_rc.data.score_normalizer import minmax_scale_s
    df = minmax_scale_s(df)
```

All downstream code (`df_pos`, `s_pos`, `s_all`, the LTT grid, WSR walk, cost function) reads
from this `df`, so everything sees consistently scaled values. `θ̂[0]` (`λ_lo`) will be
expressed in the scaled `[0, 1]` space.

This site also covers **`alpha_sweep.py`**: `run_alpha_sweep()` passes a df to
`run_calibration()`, which writes it to a temp parquet and calls `calibrate()`. Site 1 therefore
scales that temp parquet on load — no third injection site needed.

### 4. Injection Site 2 — `cascade_rc/ablations/budget_split.py::_run_topic()`

**Location:** immediately after `df = pd.read_parquet(parquet_path)` (currently line 98), before
`_compute_wss(result, df)` is called.

```python
df = pd.read_parquet(parquet_path)
if config.normalize_base_scores:
    from cascade_rc.data.score_normalizer import minmax_scale_s
    df = minmax_scale_s(df)
```

`_compute_wss()` computes `s < lam_lo` where `lam_lo = result.theta_hat[0]`. After this
injection, both `df["s"]` and `theta_hat[0]` are expressed in the same scaled coordinate system.
Without this site, the comparison is physically incoherent (threshold in `[0,1]`, data in
`[0.01, 0.03]`) and WSS would be computed incorrectly.

### 5. Config snapshot — `cascade_rc/calibration/main_calibrate.py::calibrate()`

Add `"normalize_base_scores": config.normalize_base_scores` to the `config_snapshot` dict
inside `CertificationResult`. This makes every saved certificate self-documenting about whether
scaling was active.

---

## Data-flow summary

```
parquet on disk (s ∈ [0.011, 0.032])
        │
        │ pd.read_parquet()
        ▼
  full df (all splits)
        │
        │ [if normalize_base_scores] minmax_scale_s()   ← Site 1 (calibrate) / Site 2 (budget_split)
        ▼
  df (s ∈ [0.0, 1.0])
        │
   ┌────┴────────────────────┐
   │                         │
   ▼                         ▼
calibrate()           _compute_wss()
(θ̂ in [0,1] space)   (s < λ_lo — same space ✓)
```

---

## Files changed

| File | Change |
|------|--------|
| `cascade_rc/config.py` | Add `normalize_base_scores: bool = False` to `CascadeRCConfig` |
| `cascade_rc/data/score_normalizer.py` | Add `minmax_scale_s()` function |
| `cascade_rc/calibration/main_calibrate.py` | Inject scaling after parquet load in `calibrate()`; add flag to `config_snapshot` |
| `cascade_rc/ablations/budget_split.py` | Inject scaling after parquet load in `_run_topic()` |

---

## Testing

- Unit test for `minmax_scale_s()`: verify `[0.011, 0.032]` → `[0.0, 1.0]`, idempotency on
  already-scaled data, no-op on constant-score input.
- Existing tests must pass unchanged (flag defaults off).
- Integration smoke-test: run `calibrate()` with `normalize_base_scores=True` on CD012768 and
  confirm `λ_lo > 0.0` and `WSS@95 > −0.05`.
