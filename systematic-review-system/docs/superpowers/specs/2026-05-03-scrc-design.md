# Design: Prompt 11.3 — SCRC-I and SCRC-T Baselines

**Date:** 2026-05-03
**Branch:** feature_redesignv2
**Files to create:**
- `cascade_rc/baselines/scrc.py`
- `cascade_rc/tests/test_scrc.py`

**Reference:** Xu, Guo, Wei, "Selective Conformal Risk Control", arXiv:2512.12844 (Dec 2025)
**Supporting reference:** Angelopoulos, Bates, Fisch, Lei, Schuster, "Conformal Risk Control", arXiv:2208.02814 (2022/2024)

---

## 1. Overview

SCRC adds a *selection* stage on top of standard Conformal Risk Control (CRC). For each test document the model either:
- **accepts** — provides a prediction (include in screening set), or
- **abstains** — defers to human review.

The conformal guarantee applies to the *selected* subset: among accepted documents, the false-negative rate (FNR) ≤ α with high probability, where α = 1 − target\_recall.

Two variants differ only in how they use the calibration set:

| Variant | τ fitted on | λ\* fitted on | LOO adjustment |
|---|---|---|---|
| **SCRC-I** (inductive) | C1 (first half of cal) | C2 selected (second half) | No |
| **SCRC-T** (transductive) | Full cal | Full cal selected | Yes — `n_pos+1` |

---

## 2. File Map

| File | Role |
|---|---|
| `cascade_rc/baselines/scrc.py` | `SCRC` class + `_crc_threshold()` helper + `run_sweep()` + `__main__` CLI |
| `cascade_rc/tests/test_scrc.py` | 8 tests across unit / algorithm / coverage categories |

---

## 3. `SCRC` Class

### Constructor

```python
SCRC(
    variant: Literal["I", "T"],
    alpha: float,               # risk level; driver sets alpha = 1 − target_recall
    abstain_rate: float = 0.1,  # quantile of u below which to abstain (0 → no abstention = plain CRC)
    split_ratio: float = 0.5,   # SCRC-I only: fraction of cal rows assigned to C1
    seed: int = 0,              # RNG seed for SCRC-I stratified permutation
)
```

`abstain_rate=0.0` is explicitly allowed (reduces SCRC to standard CRC on `s` alone) but is not the intended use; the paper's contribution is learnable selection.

### Fitted attributes (set by `fit()`)

| Attribute | Type | Meaning |
|---|---|---|
| `tau_` | `float` | Selection threshold on `u`; abstain if `u < tau_` |
| `lambda_star_` | `float` | CRC acceptance threshold on `s`; accept if `s ≥ lambda_star_` |
| `n_pos_used_` | `int` | Number of calibration positives used to compute `lambda_star_` (C2 for SCRC-I, full cal for SCRC-T); diagnostic and testable |

`predict()` raises `RuntimeError` if called before `fit()` (sklearn-style state machine).

### `fit(s, u, y)` — branching only here

**SCRC-I:**
1. Stratified permutation using `np.random.default_rng(seed)`:
   - Shuffle positive indices and negative indices independently.
   - Assign first `floor(n_pos * split_ratio)` positives and first `floor(n_neg * split_ratio)` negatives to C1; remainder to C2.
2. `tau_ = np.quantile(u_C1, abstain_rate)`
3. Filter C2: `selected_C2 = (u_C2 >= tau_)`
4. `lambda_star_ = _crc_threshold(sorted positive scores in selected C2, alpha)`
5. `n_pos_used_ = (y_C2[selected_C2] == 1).sum()`

**SCRC-T:**
1. `tau_ = np.quantile(u_cal, abstain_rate)`
2. Filter full cal: `selected_cal = (u_cal >= tau_)`
3. `lambda_star_ = _crc_threshold(sorted positive scores in selected cal, alpha)`
4. `n_pos_used_ = (y_cal[selected_cal] == 1).sum()`

### `predict(s, u)` — shared across variants

```python
np.where((u >= self.tau_) & (s >= self.lambda_star_), "accept", "abstain")
```

Returns an `object` dtype array with values in `{"accept", "abstain"}`.

---

## 4. `_crc_threshold` Pure Function

```python
def _crc_threshold(pos_scores: np.ndarray, alpha: float) -> float:
```

`pos_scores` must be sorted ascending. Implements the split-conformal FNR quantile:

```
k = floor(alpha * (n_pos + 1))
if n_pos == 0:   return 0.0   # no positives → accept everything
if k >= n_pos:   return 0.0   # alpha too large for n_pos → accept everything
return pos_scores[k]          # (k+1)-th smallest positive score; includes k=0 case
```

**Why this formula:** Under exchangeability of the `n_pos` calibration positives and one test positive, the rank of the test score among all `n_pos+1` is uniform on `{1,…,n_pos+1}`. Setting `λ* = pos_scores[k]` ensures:

```
P(s_test < λ* | y_test=1) = k/(n_pos+1) ≤ α
```

The `n_pos+1` denominator is the standard finite-sample LOO correction; it is the same for both SCRC-I (where `n_pos` comes from C2) and SCRC-T (where `n_pos` comes from full cal). The only difference between the variants is the size of `n_pos`.

**Pinned test values (must not drift):**
- `alpha=0.1, pos_scores=[0.1,…,1.0] (n=10)`: `k=1` → `λ* = 0.2`
- `alpha=0.05, pos_scores=[0.1,…,1.0] (n=10)`: `k=0` → `λ* = 0.1`

---

## 5. Driver (`run_sweep`)

### Output schema (48 rows: 2 variants × 4 recalls × 6 topics)

| column | dtype | notes |
|---|---|---|
| `method` | object | `"scrc_i"` or `"scrc_t"` |
| `topic_id` | object | CLEF-TAR 2019 topic ID |
| `target_recall` | float64 | 0.80 / 0.90 / 0.95 / 1.0 |
| `examined` | int64 | `(decisions == "accept").sum()` |
| `recall_achieved` | float64 | `#{y=1, accept} / #{y=1, total test}` |
| `wss_95` | float64 | via `wss_at_recall(predictions, y_true, target_recall=0.95)` |
| `wss_status` | object | `"ok"` / `"recall_target_missed"` / `"no_relevant_docs"` |
| `peak_rss_kb` | float64 | `np.nan` — SCRC has constant per-cell memory cost; column retained for schema parity with AUTOSTOP/RLStop `pd.concat`. Note: AUTOSTOP/RLStop use `int64`; pandas silently upcasts to `float64` on concat, which is correct behaviour. |

### Per-cell driver flow

```python
df = pd.read_parquet(data_dir / f"{topic_id}.parquet")
cal  = df[df["is_calib"] == 1]
test = df[df["is_calib"] == 0]

alpha = 1.0 - target_recall
scrc = SCRC(variant=variant, alpha=alpha, abstain_rate=abstain_rate)
scrc.fit(cal["s"].values, cal["u"].values, cal["y_abstract"].values)
decisions = scrc.predict(test["s"].values, test["u"].values)

examined    = int((decisions == "accept").sum())
predictions = (decisions == "accept").astype(np.int64)
y_true      = test["y_abstract"].to_numpy(dtype=np.int64)
wss         = wss_at_recall(predictions, y_true, target_recall=0.95)
```

`recall_achieved = wss["achieved_recall"]` (includes recall_target_missed cases).

### CLI

```
python -m cascade_rc.baselines.scrc \
    --data-dir     artefacts/cascade_rc/data \
    --out-dir      artefacts/baselines/scrc \
    [--topics      CD008874 CD012080 CD012768 CD011768 CD011975 CD011145] \
    [--recalls     0.80 0.90 0.95 1.0] \
    [--variants    I T] \          # default: both
    [--abstain-rate 0.1] \
    [--dry-run]
```

`--dry-run` writes a 0-row schema parquet without loading data or fitting models.

---

## 6. Tests (`test_scrc.py`)

### Category A — Unit correctness

| Test | Assertion |
|---|---|
| `test_crc_threshold_pin` | Pins the formula: `alpha=0.1 → 0.2`, `alpha=0.05 → 0.1` on a known 10-element array |
| `test_crc_threshold_no_positives` | `pos_scores=[]` → returns `0.0` |
| `test_predict_schema` | Output is `object` dtype, values ∈ `{"accept","abstain"}`, shape `(n,)` |
| `test_predict_before_fit_raises` | `RuntimeError` on unfitted model |

### Category B — Algorithm correctness

| Test | Assertion |
|---|---|
| `test_scrc_i_internal_split_pins_tau` | `tau_` == `np.quantile(u_C1, abstain_rate)` for known seed; verifies stratified split via `n_pos_used_ < y_cal.sum()` |
| `test_scrc_t_uses_more_positives_than_scrc_i` | `scrc_t.n_pos_used_ > scrc_i.n_pos_used_` (SCRC-T has full cal positives; SCRC-I has only C2) |

### Category C — Coverage simulation (1 000 trials each)

**Synthetic data per trial:** `n_cal=300, n_test=200`, `π=0.10`, positives `Beta(8,2)`, negatives `Beta(2,8)`, `u ~ Beta(5,5)` independent. `alpha=0.10`, `abstain_rate=0.1`.

**Coverage criterion:**
```python
decisions = scrc.predict(s_test, u_test)
accepted  = (decisions == "accept")
recall    = (accepted & (y_test == 1)).sum() / max(1, (y_test == 1).sum())
covered   = recall >= 1.0 - alpha
```

**Sanity guard (both tests):**
```python
# Not degenerate — not all accept, not all abstain
assert 0.05 < (decisions == "accept").mean() < 0.95
```

| Test | Assert |
|---|---|
| `test_scrc_i_marginal_coverage_1000` | `sum(covered) / 1000 >= 1 - alpha - 0.02` |
| `test_scrc_t_marginal_coverage_1000` | same |

**Why 2% tolerance:** Binomial 95% CI on true coverage 0.90 at n=1000 trials is approximately [0.881, 0.919]. The `−0.02` band equals the lower bound of that CI, so the assertion fails only when true coverage is genuinely below 0.88.

---

## 7. Acceptance Criteria

1. `artefacts/baselines/scrc/scrc_results.parquet` — 48 rows, 8 columns, correct dtypes.
2. `pd.concat([autostop_df, rlstop_df, scrc_df])` — 120 rows, no NaN in `method` column.
3. All 8 tests pass.
4. `--dry-run` writes 0-row schema parquet without fitting models.
5. `n_pos_used_` exposes diagnostic counts for downstream analysis.

---

## 8. Files Changed / Created

| File | Change |
|---|---|
| `cascade_rc/baselines/scrc.py` | **New** — SCRC class + driver |
| `cascade_rc/tests/test_scrc.py` | **New** — 8 tests |
