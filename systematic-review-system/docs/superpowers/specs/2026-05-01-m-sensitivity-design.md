# Design: m₊ Sensitivity Sweep (Prompt 9.1)

**Date:** 2026-05-01
**Branch:** feature_redesignv2
**Files to create:** `cascade_rc/ablations/m_sensitivity.py`, `cascade_rc/tests/test_m_sensitivity.py`
**Output artefact:** `artefacts/cascade_rc/ablations/m_sensitivity.parquet`

---

## Goal

Sweep `m₊ ∈ {26, 35, 50, 75, 100, full}` per topic to quantify how calibration-positive sample size affects abstention rate, WSS@95, and slack recovery (mean η̂⁻⋆). Populates the m-sensitivity figure for Phase 12.

---

## Section 1 — Data Flow & Subsampling

### Per-topic loop

1. Load the enriched topic parquet (columns: `is_calib`, `y_abstract`, `s`, `u`, `llm_y_hat`).
2. Compute `m_plus_full` = count of rows where `is_calib==1 AND y_abstract==1`.
3. Compute `N_min = ceil(ln(1/δ_LTT) / (-ln(1-α)))` from the active `LTTBudget` config.
4. **Topic skip guard:** if `m_plus_full < N_min`, log a warning and accumulate the topic ID. **Do not emit any parquet rows.** Write all accumulated skipped IDs to `skipped_topics.json` once at the end of the full sweep (not per-topic, to avoid partial overwrites). This is distinct from a per-cell abstention.
5. Build effective m-grid: `[26, 35, 50, 75, 100, m_plus_full]`, keep only values `≤ m_plus_full`, deduplicate.
6. For each `m` in the grid, run calibration (see below) and collect one result row.

### Subsampling policy

**Seed derivation (nested subsets):**
```python
rng = np.random.default_rng(hash((topic_id, global_seed)) & 0xFFFFFFFF)
permuted = rng.permutation(cal_pos_indices)   # one permutation per topic
sampled_at_m = permuted[:m]                   # m=26 is a strict prefix of m=50
```
`m` is intentionally excluded from the hash so smaller cells are prefixes of larger ones, minimising curve noise.

**What happens to unsampled calibration positives:** they are **dropped entirely** (not reassigned to test). The test split must remain identical across all m-cells so WSS comparisons are valid.

**Fast path:** when `m == m_plus_full`, pass the original parquet path to `calibrate()` — no temp file needed.

**Otherwise:** write subsampled DataFrame to a `tempfile.NamedTemporaryFile` parquet and pass that path to `calibrate()`. The temp file is deleted immediately after `calibrate()` returns.

---

## Section 2 — Output Schema

### Parquet: `artefacts/cascade_rc/ablations/m_sensitivity.parquet`

| column | dtype | meaning |
|---|---|---|
| `topic_id` | str | e.g. `"CD008874"` |
| `m_target` | int64 | requested grid value (26 / 35 / 50 / 75 / 100 / m_plus_full); the "full" entry stores the integer value of m_plus_full — no string sentinel in the parquet |
| `m_actual` | int64 | positives actually passed to `calibrate()` |
| `abstention` | bool | True if `calibrate()` returned abstain status |
| `wss_95` | float64 | WSS@95 via `wss_at_recall`; NaN if abstained or recall missed |
| `wss_status` | str | `"ok"` / `"recall_target_missed"` / `"abstained"` |
| `achieved_recall` | float64 | test-set recall under θ̂; NaN if abstained |
| `mean_eta_lcb` | float64 | `np.mean(result.eta_lcb_grid)`; NaN if abstained |

### Audit file: `artefacts/cascade_rc/ablations/skipped_topics.json`

```json
["CD012768", ...]
```

Topics where `m_plus_full < N_min`. No calibration attempted.

### Metric definitions

**WSS@95** — Cohen et al. (2006) workload saved at 95% recall:
```
WSS@r = (TN + FN) / N − (1 − r)
```
Computed via `cascade_rc.evaluation.metrics.wss_at_recall(predictions, y_test, target_recall=0.95)`.

Routing under θ̂ = (λ̂_lo, λ̂_hi, τ̂_SE) applied to test rows (is_calib==0):
```python
auto_reject  = s < lambda_lo
auto_accept  = s >= lambda_hi
llm_escalate = (lambda_lo <= s) & (s < lambda_hi) & (u >= tau_SE)
# predictions: 1 = human/LLM must screen, 0 = auto-rejected
predictions  = (~auto_reject).astype(int)
```
Auto-rejected positives are false negatives; `wss_at_recall` captures this via `achieved_recall < 0.95 → status="recall_target_missed"`.

**mean η̂⁻⋆** — `np.mean(result.eta_lcb_grid)` — summarises slack recovery across the full θ-grid. Expected to rise monotonically with m.

---

## Section 3 — CLI

Entry point: `python -m cascade_rc.ablations.m_sensitivity`

```
--data-dir   DIR    Enriched topic parquets (default: artefacts/cascade_rc/data/)
--out-dir    DIR    Output root (default: artefacts/cascade_rc/ablations/)
--seed       INT    Global RNG seed (default: 42)
--topics     IDS    Space-separated topic IDs to restrict sweep (default: all)
--dry-run           Emit schema-only parquet + empty skipped_topics.json; no calibration
--n-jobs     INT    Parallel topic workers (default: 1)
```

**`--dry-run` behaviour:** build empty DataFrame with exact column dtypes, write `m_sensitivity.parquet`, write `skipped_topics.json: []`, exit. No `calibrate()` calls, no temp files.

**Parallelism:** `joblib.Parallel(n_jobs=n_jobs, backend="loky")` over topics. `backend="loky"` is pinned explicitly for process-based parallelism (avoids GIL-bound threading with numpy-heavy workloads).

---

## Section 4 — Plots

**Per-topic figure** saved to `artefacts/cascade_rc/ablations/plots/m_sensitivity_{topic_id}.png`:

```python
fig, axes = plt.subplots(3, 1, sharex=True, figsize=(6, 8))
axes[0].plot(...)      # top:    WSS@95 curve
axes[1].plot(...)      # middle: mean η̂⁻⋆ curve
axes[2].step(...)      # bottom: abstention indicator (binary step plot)
axes[2].set_xlabel("m_actual (positives in calibration)")
```

Marker coding: `wss_status="ok"` → blue circle; `"recall_target_missed"` → red ✗; abstained cells omitted from WSS and η̂ lines.

**Combined overview figure** (`m_sensitivity_overview.png`): all topics overlaid per subplot (faded individual lines + bold median line), same 3-subplot layout.

---

## Section 5 — Tests (`cascade_rc/tests/test_m_sensitivity.py`)

| test | what it verifies |
|---|---|
| `test_dry_run_schema` | `--dry-run` writes zero-row parquet with exact column names and dtypes |
| `test_nested_subsamples` | for synthetic topic m₊=100: `sampled[:26]` is a strict prefix of `sampled[:50]` (nested seed policy) |
| `test_skip_low_prevalence_topic` | topic with `m_plus_full < N_min` produces zero parquet rows and appears in `skipped_topics.json` |
| `test_wss_routed_correctly` | fabricated parquet + known θ̂ → `wss_at_recall` called with correct `predictions` vector |

---

## Acceptance Criteria

1. `m_sensitivity.parquet` has columns `topic_id, m_target, m_actual, abstention, wss_95, wss_status, achieved_recall, mean_eta_lcb` with correct dtypes.
2. `--dry-run` produces the schema without launching any calibration.
3. All four tests pass.
4. Per-topic plots and overview plot are written to `artefacts/cascade_rc/ablations/plots/`.
