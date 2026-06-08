# Design: Prompt 10.1 — Two Ablation Sweeps

**Date:** 2026-05-02
**Branch:** feature_redesignv2
**Files to create:** `cascade_rc/ablations/budget_split.py`, `cascade_rc/ablations/walk_ordering.py`
**File to modify:** `cascade_rc/calibration/main_calibrate.py`, `cascade_rc/config.py`

---

## 1. Shared Change: `calibrate()` `order_fn` Parameter

`cascade_rc/calibration/main_calibrate.py:calibrate()` gets one new optional parameter:

```python
def calibrate(
    topic_id: str,
    calib_parquet: Path,
    config: CascadeRCConfig,
    artefact_dir: Path | None = None,
    chunk_size: int = 500,
    order_fn: Callable[[np.ndarray], np.ndarray] | None = None,
) -> "CertificationResult | tuple[None, None, str]":
```

Line 199 (`order = safest_to_riskiest_order(theta_g)`) becomes:

```python
order = (order_fn if order_fn is not None else safest_to_riskiest_order)(theta_g)
```

All existing callers (`m_sensitivity.py`, tests, CLI) are unaffected — the parameter defaults to `None` which preserves the original behaviour.

---

## 2. Validator Fix: `LTTBudget._check_delta_split`

Replace the current absolute-difference check with `math.isclose` to handle IEEE-754 precision when constructing `LTTBudget` with ablation pairs such as `(0.03, 0.07)`:

```python
import math

@model_validator(mode="after")
def _check_delta_split(self) -> "LTTBudget":
    if not math.isclose(self.delta_eta + self.delta_LTT, self.delta_total, abs_tol=1e-9):
        raise ValueError(
            f"delta_eta ({self.delta_eta}) + delta_LTT ({self.delta_LTT}) "
            f"must equal delta_total ({self.delta_total})"
        )
    return self
```

This is a correctness fix, not a workaround. Ablations construct `LTTBudget` with explicit args — the validator will pass for all 5 pairs because they sum to 0.10. The fix also protects against future floating-point inputs.

---

## 3. Module: `cascade_rc/ablations/budget_split.py`

### Purpose

Sweep `(δ_η, δ_LTT)` budget splits across the 3 headline DTA topics to characterise how the η/LTT budget allocation affects `|Λ̂|` (certified set size) and `WSS@95`.

### Sweep Parameters

```python
HEADLINE_DTA_TOPICS: list[str] = ["CD008874", "CD012080", "CD012768"]

BUDGET_SPLITS: list[tuple[float, float]] = [
    (0.01, 0.09),
    (0.03, 0.07),
    (0.05, 0.05),   # default (symmetric)
    (0.07, 0.03),
    (0.09, 0.01),
]
```

Total runs: 5 splits × 3 topics = **15 calibration runs**.

### Config Patching

For each `(delta_eta, delta_ltt)` pair, construct a fresh `LTTBudget` (the validator passes because all pairs sum to 0.10):

```python
patched_ltt = LTTBudget(
    delta_eta=delta_eta,
    delta_LTT=delta_ltt,
    delta_total=0.10,
    alpha=config.ltt.alpha,
    K=config.ltt.K,
    c_human=config.ltt.c_human,
    c_llm=config.ltt.c_llm,
)
patched_config = config.model_copy(update={"ltt": patched_ltt})
```

No subprocess overhead; stays in-process and consistent with `m_sensitivity.py`.

### Parquet Schema

Output: `artefacts/cascade_rc/ablations/budget_split.parquet`

| column | dtype | notes |
|---|---|---|
| `delta_eta` | float64 | η budget share |
| `delta_ltt` | float64 | LTT budget share |
| `topic_id` | object | |
| `m_plus` | int64 | calibration positives |
| `abstention` | bool | True if calibrate() returned tuple |
| `wss_95` | float64 | NaN on abstention |
| `wss_status` | object | "ok" \| "recall_target_missed" \| "abstained" |
| `achieved_recall` | float64 | NaN on abstention |
| `n_certified` | int64 | \|Λ̂\|; 0 on abstention |
| `mean_eta_lcb` | float64 | mean η̂⁻⋆ across grid |
| `theta_hat_lambda_lo` | float64 | NaN on abstention |
| `theta_hat_lambda_hi` | float64 | NaN on abstention |
| `theta_hat_tau_se` | float64 | NaN on abstention |
| `alpha_dagger_at_theta` | float64 | α + η̂⁻⋆(θ̂); NaN on abstention |

`wss_status` and `achieved_recall` match the Phase 9 `m_sensitivity` schema for Phase 12 figure compatibility.

### Pareto Plot

Output: `artefacts/cascade_rc/ablations/plots/budget_split_pareto.png`

- **X** = `n_certified` (size of Λ̂) — operational efficiency
- **Y** = `wss_95` — deployment metric
- **Color** = `delta_eta` (5 values mapped to a sequential colormap)
- **Marker shape** = topic (3 shapes, e.g., o / s / ^)
- **Failed cells** (`wss_status != "ok"`) → red ✗ markers
- **Inset** = 5×3 binary heatmap of `abstention` (split × topic), placed in top-right corner

### Code Structure

```python
HEADLINE_DTA_TOPICS: list[str] = [...]
BUDGET_SPLITS: list[tuple[float, float]] = [...]
PARQUET_SCHEMA: dict[str, str] = {...}

def _run_topic(topic_id, parquet_path, delta_eta, delta_ltt, config, out_dir) -> dict
def _plot_pareto(df, out_dir) -> None
def run_sweep(data_dir, out_dir, topics_filter, n_jobs, dry_run) -> pd.DataFrame
def main() -> None   # argparse CLI
```

`run_sweep` uses `joblib.Parallel(backend="loky")` over `(topic, split)` pairs.

### CLI

```
python -m cascade_rc.ablations.budget_split \
  --data-dir artefacts/cascade_rc/data \
  --out-dir  artefacts/cascade_rc/ablations \
  [--topics CD008874 CD012080 CD012768] \
  [--n-jobs 4] \
  [--dry-run]
```

---

## 4. Module: `cascade_rc/ablations/walk_ordering.py`

### Purpose

Compare four walk-ordering strategies to empirically validate Lemma 6 (safest-to-riskiest is optimal) and characterise how ordering affects `|Λ̂|` and `WSS@95`.

### Orderings

```python
# 1. Default — Lemma 6 baseline
def _order_safest_to_riskiest(grid: np.ndarray) -> np.ndarray:
    return safest_to_riskiest_order(grid)   # existing function

# 2. Reverse — validates Lemma 6 by showing the bad direction
def _order_riskiest_to_safest(grid: np.ndarray) -> np.ndarray:
    return safest_to_riskiest_order(grid)[::-1]

# 3. Lex τ_SE primary — alternative valid ordering
def _order_lex_tau_se_first(grid: np.ndarray) -> np.ndarray:
    return np.lexsort((grid[:, 0], grid[:, 1], grid[:, 2]))

# 4. Random — 5 seeds, reported as distribution
def _order_random(grid: np.ndarray, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).permutation(len(grid))
```

**Random seeds:** `[42, 43, 44, 45, 46]` — 5 realisations per topic to avoid single-seed luck.

### Run Matrix

| order_name | seeds | runs per topic | total rows |
|---|---|---|---|
| safest_to_riskiest | — | 1 | 3 |
| riskiest_to_safest | — | 1 | 3 |
| lex_tau_se_first | — | 1 | 3 |
| random | 42–46 | 5 | 15 |
| **Total** | | | **24** |

### Parquet Schema

Output: `artefacts/cascade_rc/ablations/walk_ordering.parquet`

| column | dtype | notes |
|---|---|---|
| `order_name` | object | "safest_to_riskiest" \| "riskiest_to_safest" \| "lex_tau_se_first" \| "random" |
| `order_seed` | int64 | 42–46 for random; -1 (sentinel) for deterministic |
| `topic_id` | object | |
| `m_plus` | int64 | |
| `abstention` | bool | |
| `wss_95` | float64 | |
| `wss_status` | object | |
| `achieved_recall` | float64 | |
| `n_certified` | int64 | |
| `mean_eta_lcb` | float64 | |
| `theta_hat_lambda_lo` | float64 | |
| `theta_hat_lambda_hi` | float64 | |
| `theta_hat_tau_se` | float64 | |
| `alpha_dagger_at_theta` | float64 | |

### Plots

**`walk_ordering_n_certified.png`** — grouped bar chart:
- X = topic (3 groups)
- Bars = deterministic orderings (one bar each) + random (mean bar with ±1 std error bars)
- Y = `n_certified`
- Expected pattern: `riskiest_to_safest` collapses to 0; `safest_to_riskiest` highest

**`walk_ordering_wss_95.png`** — same layout:
- Y = `wss_95`
- Failed cells (`wss_status != "ok"`) rendered as red ✗ above bar
- Expected pattern: `safest_to_riskiest` ≥ random WSS@95 on ≥2/3 topics (acceptance criterion)

### Code Structure

```python
HEADLINE_DTA_TOPICS: list[str] = [...]
RANDOM_SEEDS: list[int] = [42, 43, 44, 45, 46]
DETERMINISTIC_ORDERS: dict[str, Callable] = {...}
PARQUET_SCHEMA: dict[str, str] = {...}

def _run_topic(topic_id, parquet_path, order_name, order_fn, order_seed, config, out_dir) -> dict
def _plot_n_certified(df, out_dir) -> None
def _plot_wss_95(df, out_dir) -> None
def run_sweep(data_dir, out_dir, topics_filter, n_jobs, dry_run) -> pd.DataFrame
def main() -> None
```

`run_sweep` uses `joblib.Parallel(backend="loky")` over `(topic, order_name, seed)` triples, passing `order_fn` to `calibrate()`. Each run gets an isolated `artefact_dir` subdirectory keyed by `{topic_id}_{order_name}_{seed}` to prevent checkpoint collisions between orderings.

### CLI

```
python -m cascade_rc.ablations.walk_ordering \
  --data-dir artefacts/cascade_rc/data \
  --out-dir  artefacts/cascade_rc/ablations \
  [--topics CD008874 CD012080 CD012768] \
  [--n-jobs 4] \
  [--dry-run]
```

---

## 5. Acceptance Criteria

1. `artefacts/cascade_rc/ablations/budget_split.parquet` exists with 15 rows and all 14 columns at correct dtypes.
2. `artefacts/cascade_rc/ablations/walk_ordering.parquet` exists with 24 rows and all 14 columns at correct dtypes.
3. `safest_to_riskiest` achieves `wss_95` ≥ `random` mean on ≥2/3 headline DTA topics (Lemma 6 sanity check).
4. Both `--dry-run` flags write schema-only parquets without calling `calibrate()`.
5. All existing tests pass (no regression from `order_fn` param or validator fix).

---

## 6. Files Changed / Created

| file | change |
|---|---|
| `cascade_rc/config.py` | Validator: `abs(...)` → `math.isclose(...)` |
| `cascade_rc/calibration/main_calibrate.py` | Add `order_fn` param; update `Callable` import |
| `cascade_rc/ablations/budget_split.py` | **New** |
| `cascade_rc/ablations/walk_ordering.py` | **New** |
