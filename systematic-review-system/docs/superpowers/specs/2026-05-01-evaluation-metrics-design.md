# Prompt 8.1 — Evaluation Metrics Design

**Date:** 2026-05-01
**Scope:** `cascade_rc/evaluation/`, `cascade_rc/baselines/tar_eval_vendor/`, `cascade_rc/tests/test_metrics.py`

---

## 1. Goals

Provide four pure metric functions (WSS@95, abstention rate, LLM query volume, slack-ratio diagnostic) that Phase 12 figures and Phase 9's m-sensitivity sweep can consume without touching calibration internals. A per-topic CLI entry point emits a single JSON line for integration tests and CI dashboards.

---

## 2. File Layout

**New files:**
```
cascade_rc/evaluation/__init__.py
cascade_rc/evaluation/metrics.py          # pure functions + CLI main()
cascade_rc/evaluation/tar_eval_wrapper.py # subprocess wrapper for vendored CLEF script
cascade_rc/baselines/__init__.py
cascade_rc/baselines/tar_eval_vendor/
    tar_eval.py                           # vendored CLEF BSD-3 script (committed)
    VENDORED_FROM                         # source URL + commit SHA + license note
cascade_rc/tests/test_metrics.py
```

**Modified files:**
```
cascade_rc/certificates/store.py          # add slack_mat field to CertificationResult
cascade_rc/calibration/main_calibrate.py  # pass slack_mat when constructing CertificationResult
cascade_rc/config.py                      # add delta_bootstrap: float = 0.05 to LTTBudget
```

---

## 3. `CertificationResult` Change

Add one field to the dataclass in `store.py`:

```python
slack_mat: np.ndarray   # (G, m_plus) — persisted in pkl only, excluded from JSON summary
```

`CertificateStore.save()` already pickle-dumps the full dataclass, so no change to the serialisation logic. The JSON summary block does **not** include `slack_mat` (it is a ~8 000 × 121 float64 matrix and would bloat the sidecar file). In `main_calibrate.py`, `slack_mat` is already in scope at the `CertificationResult(...)` construction site.

---

## 4. Config Change

Add `delta_bootstrap` to `LTTBudget` in `config.py`:

```python
delta_bootstrap: float = 0.05
```

The bootstrap confidence level for `bootstrap_eta_upper` must match or be explicitly set relative to the WSR-LCB level so the slack-ratio diagnostic is not apples-to-oranges.

---

## 5. Pure Functions in `metrics.py`

### 5.1 `wss_at_recall`

```python
def wss_at_recall(
    predictions: np.ndarray,   # 1=screen, 0=skip
    y_true: np.ndarray,
    target_recall: float = 0.95,
) -> dict:
```

Computes the CLEF/Cohen-2006 formula `WSS@r = (TN + FN) / N − (1 − r)`.

Returns a dict with three keys:
- `"wss"` — float (or `float("nan")` if recall target missed)
- `"achieved_recall"` — float
- `"status"` — `"ok"` | `"recall_target_missed"`

Returns `status="recall_target_missed"` (with `wss=nan`) when `achieved_recall < target_recall`. This is a tagged failure — not a silent NaN — so downstream figure code can distinguish a genuine 0.0 WSS from a certification failure.

**Monotonicity property (tested):** for fixed `predictions` with `achieved_recall >= r`, `wss` is strictly increasing in `target_recall` because `(1 − r)` decreases as `r` rises.

### 5.2 `abstention_rate`

```python
def abstention_rate(certified: dict[str, dict]) -> float:
```

`certified` maps `topic_id → {"status": "certified"|"abstained", ...}`. Returns `mean(status == "abstained")`. Intended for multi-topic callers (Phase 9 sweep); the per-topic CLI emits `cert.status` directly, not this function.

### 5.3 `llm_query_volume`

```python
def llm_query_volume(routing: pd.DataFrame) -> dict:
```

Routing DataFrame schema: columns `{pmid: str, decision: str}` where `decision ∈ {auto_accept, auto_reject, llm_escalate, human_review}`. Returns:

```python
{
  "auto_accept": int,
  "auto_reject": int,
  "llm_escalate": int,
  "human_review": int,
  "total": int,
  "llm_fraction": float,   # llm_escalate / total
}
```

Raises `ValueError` if any unexpected `decision` value is encountered.

### 5.4 `slack_ratio_diagnostic`

```python
def slack_ratio_diagnostic(
    eta_lcb: np.ndarray,        # (G,) η̂⁻⋆ from cert
    eta_boot_upper: np.ndarray, # (G,) bootstrap upper bound
) -> np.ndarray:                # (G,) element-wise ratio
```

Returns element-wise `eta_lcb / eta_boot_upper`. Values ≈ 1 mean the WSR LCB is tight; values << 1 mean the bound is conservative (the paper calls this the §9.4 tightness diagnostic).

### 5.5 `bootstrap_eta_upper`

```python
def bootstrap_eta_upper(
    slack_mat: np.ndarray,  # (G, m_plus) from cert.slack_mat
    delta: float,           # from config.ltt.delta_bootstrap
    B: int = 1000,
    seed: int = 0,
) -> np.ndarray:            # (G,) upper confidence bounds
```

For each grid point `g`, draws `B` bootstrap samples of `slack_mat[g]` (sampling along axis 1 of the `(G, m_plus)` matrix), computes the mean of each bootstrap sample, returns the `(1 − delta)`-quantile of those means as the upper bound. Fully vectorized over `G`: use `rng.integers(0, m_plus, size=(G, B, m_plus))` to index then take `mean(axis=-1)` → `(G, B)` boot means → `quantile(1-delta, axis=1)` → `(G,)`. No Python loop over grid points.

---

## 6. `tar_eval_wrapper.py`

```python
REQUIRED_KEYS: frozenset[str] = frozenset({"wss_100", "wss_95", "recall", "norm_area", "min_returned"})

def run_tar_eval(
    qrels_file: Path,
    results_file: Path,
    timeout: int = 300,
) -> dict[str, float]:
```

- Calls vendored `cascade_rc/baselines/tar_eval_vendor/tar_eval.py` via `subprocess.run(..., capture_output=True, timeout=timeout)`.
- Captures both stdout and stderr; logs stderr at `WARNING` level so CLEF diagnostic messages surface in CI logs.
- Parses stdout with a schema-based parser (splits on `:` or `=`, converts values to float); raises `ValueError` loudly if any key in `REQUIRED_KEYS` is absent from the parsed output.
- `VENDORED_FROM` commits: source URL, commit SHA, license (BSD-3-Clause).

---

## 7. CLI (`main()` in `metrics.py`)

```
python -m cascade_rc.evaluation.metrics \
    --topic CD008874 \
    [--artefact-dir artefacts/cascade_rc] \
    [--calib-parquet artefacts/cascade_rc/data/CD008874.parquet]
```

Steps:

1. Load `CertificationResult` pkl via `CertificateStore.load(topic, artefact_dir)`.
2. Load scoring parquet (path derived from `artefact_dir/data/{topic}.parquet` or `--calib-parquet`).
3. Derive routing: apply `theta_hat = (λ_lo, λ_hi, τ_SE)` to `(s, u)` columns → `decision` column. Write routing parquet to `artefact_dir/routing/{topic}.parquet`.
4. Call `llm_query_volume(routing_df)`.
5. Call `wss_at_recall(predictions, y_true)` where `predictions` comes from `decision ∈ {auto_accept, llm_escalate, human_review}` → 1, else 0; `y_true` from parquet `y_abstract`. **Filter to test rows only (`is_calib=0`)** — evaluating on the calibration set would be circular since θ̂ was derived from it.
6. Call `bootstrap_eta_upper(cert.slack_mat, delta=cfg.ltt.delta_bootstrap)` → `eta_boot`.
7. Call `slack_ratio_diagnostic(cert.eta_lcb_grid, eta_boot)` → summarize as `mean` and `std`.
8. Emit one JSON line to stdout:
   ```json
   {
     "topic": "CD008874",
     "status": "certified",
     "wss95": {"wss": 0.72, "achieved_recall": 0.96, "status": "ok"},
     "llm_volume": {"auto_accept": 12, "auto_reject": 98, "llm_escalate": 5, "human_review": 6, "total": 121, "llm_fraction": 0.041},
     "slack_ratio_mean": 0.88,
     "slack_ratio_std": 0.04
   }
   ```
   Note: `abstention_rate` is **not** in the per-topic JSON; it is a multi-topic aggregate for Phase 9.

---

## 8. Tests (`test_metrics.py`)

Two test cases required:

1. **Monotonicity:** For fixed predictions achieving recall >= 0.99, `wss_at_recall(p, y, 0.70)["wss"] < wss_at_recall(p, y, 0.95)["wss"]`.
2. **Hand-computed example:** 10-document corpus, 3 positives. Screen 5, skip 5; 3 positives are all in screened set → recall=1.0, TN=4, FN=0. `WSS@0.95 = (4+0)/10 − (1−0.95) = 0.40 − 0.05 = 0.35`.

---

## 9. Out of Scope

- `abstention_rate` multi-topic aggregation driver (Phase 9).
- Running `run_tar_eval` from the CLI (it is a separate cross-paper comparison tool, invoked manually).
- Ranking-based WSS (score-threshold sweep); the current function takes pre-thresholded binary predictions from the certified θ̂.
