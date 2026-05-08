# Min-Max Score Scaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject a configurable, rank-preserving min-max affine scaling of the `s` column at data-load time so the LTT walk grid recovers full `[0,1]` resolution on squashed-score topics (e.g. CD012768 where `s ∈ [0.011, 0.032]`).

**Architecture:** A single `minmax_scale_s()` helper in `score_normalizer.py` is called at two injection sites — `calibrate()` and `budget_split._run_topic()` — gated behind `CascadeRCConfig.normalize_base_scores: bool = False`. Min/max are always derived from the full dataframe (all splits) immediately on load; the same constants apply to every split so calibration thresholds and WSS test-set comparisons share one coordinate system.

**Tech Stack:** Python 3.11, pandas, pydantic-settings (`CascadeRCConfig`), pytest.

---

## File map

| File | Action | Responsibility |
|------|--------|---------------|
| `cascade_rc/data/score_normalizer.py` | Modify | Add `minmax_scale_s()` public function |
| `cascade_rc/config.py` | Modify | Add `normalize_base_scores: bool = False` to `CascadeRCConfig` |
| `cascade_rc/calibration/main_calibrate.py` | Modify | Inject scaling after parquet load; add flag to `config_snapshot` |
| `cascade_rc/ablations/budget_split.py` | Modify | Inject scaling after parquet load in `_run_topic()` |
| `cascade_rc/tests/test_score_normalizer.py` | Modify | Add unit tests for `minmax_scale_s()` |
| `cascade_rc/tests/test_main_calibrate_synthetic.py` | Modify | Add integration test for scaled `calibrate()` run |
| `cascade_rc/tests/test_budget_split.py` | Modify | Add mock-based test for scaled `_run_topic()` |

---

## Task 1: `minmax_scale_s()` — tests then implementation

**Files:**
- Modify: `cascade_rc/tests/test_score_normalizer.py`
- Modify: `cascade_rc/data/score_normalizer.py`

- [ ] **Step 1: Write the three failing tests**

Append to `cascade_rc/tests/test_score_normalizer.py`:

```python
# ---------------------------------------------------------------------------
# test_minmax_scale_s
# ---------------------------------------------------------------------------

import pandas as pd


def test_minmax_scale_s_squashed_range() -> None:
    """Squashed range [0.011, 0.032] is mapped to [0.0, 1.0]."""
    from cascade_rc.data.score_normalizer import minmax_scale_s

    rng = np.random.default_rng(0)
    s_raw = rng.uniform(0.011, 0.032, 200)
    df = pd.DataFrame({"s": s_raw, "y_abstract": rng.integers(0, 2, 200)})
    df_scaled = minmax_scale_s(df)

    assert df_scaled is not df, "Must return a copy, not mutate in-place"
    assert float(df_scaled["s"].min()) == pytest.approx(0.0, abs=1e-12)
    assert float(df_scaled["s"].max()) == pytest.approx(1.0, abs=1e-12)
    # rank preservation: Spearman = 1.0
    from scipy.stats import spearmanr
    rho, _ = spearmanr(df["s"].values, df_scaled["s"].values)
    assert rho == pytest.approx(1.0, abs=1e-10)


def test_minmax_scale_s_idempotent() -> None:
    """Scaling already-[0,1] data is a no-op (identity transform)."""
    from cascade_rc.data.score_normalizer import minmax_scale_s

    rng = np.random.default_rng(1)
    s_full = rng.uniform(0.0, 1.0, 100)
    df = pd.DataFrame({"s": s_full})
    df_twice = minmax_scale_s(minmax_scale_s(df))
    np.testing.assert_allclose(df_twice["s"].values, df["s"].values, atol=1e-12)


def test_minmax_scale_s_constant_noop() -> None:
    """Constant s column (s_min == s_max) returns the dataframe unchanged."""
    from cascade_rc.data.score_normalizer import minmax_scale_s

    df = pd.DataFrame({"s": [0.02] * 50})
    df_out = minmax_scale_s(df)
    # must not raise, must not produce NaN
    assert not df_out["s"].isna().any()
    np.testing.assert_array_equal(df_out["s"].values, df["s"].values)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest cascade_rc/tests/test_score_normalizer.py::test_minmax_scale_s_squashed_range \
    cascade_rc/tests/test_score_normalizer.py::test_minmax_scale_s_idempotent \
    cascade_rc/tests/test_score_normalizer.py::test_minmax_scale_s_constant_noop \
    -v 2>&1 | tail -12
```

Expected: `ImportError` or `AttributeError` — `minmax_scale_s` does not exist yet.

- [ ] **Step 3: Implement `minmax_scale_s()` in `score_normalizer.py`**

Append the following block to `cascade_rc/data/score_normalizer.py`, after the `apply_platt` function and before the `_reliability_plot` helper (i.e., after line 306 and before the `# CLI helpers` comment):

```python
def minmax_scale_s(df: pd.DataFrame) -> pd.DataFrame:
    """Rank-preserving min-max scale the 's' column to [0, 1].

    Computes s_min and s_max from ALL rows immediately on load — never from a
    filtered split — so every split stays in the same coordinate system.
    No-op when all scores are identical (avoids divide-by-zero).
    Logs original [min, max] and mean for paper reporting.
    """
    s_min = float(df["s"].min())
    s_max = float(df["s"].max())
    s_mean = float(df["s"].mean())
    if s_max > s_min:
        logger.debug(
            "Scaling s-scores. Original: [%.4f, %.4f], Mean: %.4f → New: [0.0, 1.0]",
            s_min, s_max, s_mean,
        )
        df = df.copy()
        df["s"] = (df["s"] - s_min) / (s_max - s_min)
    else:
        logger.debug("minmax_scale_s: constant s=%.4f — no-op.", s_min)
    return df
```

- [ ] **Step 4: Run all score normalizer tests**

```bash
python3 -m pytest cascade_rc/tests/test_score_normalizer.py -v 2>&1 | tail -15
```

Expected: `8 passed` (5 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/data/score_normalizer.py cascade_rc/tests/test_score_normalizer.py
git commit -m "feat(normalizer): add minmax_scale_s() with debug logging and rank-preservation tests"
```

---

## Task 2: `normalize_base_scores` config flag

**Files:**
- Modify: `cascade_rc/config.py`
- Modify: `cascade_rc/tests/test_score_normalizer.py` (one additional test appended)

- [ ] **Step 1: Write the failing test**

Append to `cascade_rc/tests/test_score_normalizer.py`:

```python
# ---------------------------------------------------------------------------
# test_normalize_base_scores_config_flag
# ---------------------------------------------------------------------------

def test_config_normalize_base_scores_defaults_false() -> None:
    """CascadeRCConfig.normalize_base_scores defaults to False."""
    from cascade_rc.config import CascadeRCConfig

    cfg = CascadeRCConfig()
    assert cfg.normalize_base_scores is False


def test_config_normalize_base_scores_can_be_set_true() -> None:
    """CascadeRCConfig.normalize_base_scores can be set to True."""
    from cascade_rc.config import CascadeRCConfig

    cfg = CascadeRCConfig(normalize_base_scores=True)
    assert cfg.normalize_base_scores is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest cascade_rc/tests/test_score_normalizer.py::test_config_normalize_base_scores_defaults_false \
    cascade_rc/tests/test_score_normalizer.py::test_config_normalize_base_scores_can_be_set_true \
    -v 2>&1 | tail -8
```

Expected: `AttributeError: 'CascadeRCConfig' object has no attribute 'normalize_base_scores'`

- [ ] **Step 3: Add the flag to `CascadeRCConfig`**

In `cascade_rc/config.py`, add one line inside `CascadeRCConfig` after `n_jobs_calib`:

```python
    n_jobs_calib: int = -1     # joblib workers for calibration grid (-1 = all cores)
    normalize_base_scores: bool = False  # pre-calibration rank-preserving min-max scaling of s
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest cascade_rc/tests/test_score_normalizer.py -v 2>&1 | tail -15
```

Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/config.py cascade_rc/tests/test_score_normalizer.py
git commit -m "feat(config): add normalize_base_scores flag to CascadeRCConfig"
```

---

## Task 3: Inject scaling in `calibrate()` and add to `config_snapshot`

**Files:**
- Modify: `cascade_rc/calibration/main_calibrate.py` (two locations)
- Modify: `cascade_rc/tests/test_main_calibrate_synthetic.py`

- [ ] **Step 1: Write the failing integration test**

Open `cascade_rc/tests/test_main_calibrate_synthetic.py` and **append** the following test (do not replace existing content):

```python
# ---------------------------------------------------------------------------
# test_calibrate_normalize_base_scores
# ---------------------------------------------------------------------------

def _make_squashed_parquet(tmp_path: Path) -> Path:
    """Write a synthetic parquet with s ∈ [0.011, 0.032] to tmp_path."""
    import pandas as pd
    import numpy as np

    rng = np.random.default_rng(42)
    n = 300
    # Three-way split: is_split=0 (60), is_split=1 (150), is_split=2 (90)
    is_split = np.array([0] * 60 + [1] * 150 + [2] * 90, dtype=np.int8)
    y = np.zeros(n, dtype=np.int64)
    # Place 12 positives in split-0, 30 in split-1, 18 in split-2
    y[:12] = 1
    y[60:90] = 1
    y[210:228] = 1

    df = pd.DataFrame({
        "pmid": [str(i) for i in range(n)],
        "s": rng.uniform(0.011, 0.032, n),  # squashed range
        "u": rng.uniform(0.0, 1.0, n),
        "y_abstract": y,
        "llm_y_hat": rng.integers(0, 2, n, dtype=np.int64),
        "is_split": is_split,
    })
    path = tmp_path / "CD_synthetic.parquet"
    df.to_parquet(path, index=False)
    return path


def test_calibrate_config_snapshot_contains_normalize_flag(tmp_path: Path) -> None:
    """calibrate() persists normalize_base_scores in config_snapshot."""
    import sys
    from pathlib import Path as _Path

    _root = _Path(__file__).parent.parent.parent.resolve()
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    from cascade_rc.calibration.main_calibrate import calibrate
    from cascade_rc.config import CascadeRCConfig, LTTBudget

    parquet_path = _make_squashed_parquet(tmp_path)

    cfg = CascadeRCConfig(
        normalize_base_scores=True,
        n_jobs_calib=1,
        ltt=LTTBudget(
            alpha=0.10,
            delta_total=0.10,
            delta_eta=0.03,
            delta_LTT=0.07,
            K=3,
            B=3,
            ensemble_temperature=0.7,
            c_human=5.0,
            c_llm=0.001,
            delta_bootstrap=0.05,
        ),
    )

    result = calibrate(
        topic_id="CD_synthetic",
        calib_parquet=parquet_path,
        config=cfg,
        artefact_dir=tmp_path,
    )

    # Must not abstain — we have 30 positives in is_split==1 which exceeds N_min=26
    assert not isinstance(result, tuple), (
        f"calibrate() abstained unexpectedly: {result}"
    )
    assert result.config_snapshot["normalize_base_scores"] is True
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
python3 -m pytest "cascade_rc/tests/test_main_calibrate_synthetic.py::test_calibrate_config_snapshot_contains_normalize_flag" \
    -v 2>&1 | tail -10
```

Expected: `KeyError: 'normalize_base_scores'` (key not yet in config_snapshot).

- [ ] **Step 3: Inject scaling in `calibrate()` — after line 166**

In `cascade_rc/calibration/main_calibrate.py`, locate the line `df = pd.read_parquet(calib_parquet)` (line 166). Replace it with:

```python
    df = pd.read_parquet(calib_parquet)
    if config.normalize_base_scores:
        from cascade_rc.data.score_normalizer import minmax_scale_s
        df = minmax_scale_s(df)
```

- [ ] **Step 4: Add `normalize_base_scores` to `config_snapshot` — lines 319-326**

Locate the `config_snapshot={` dict (lines 319–326). Add one key before the closing brace:

```python
        config_snapshot={
            "alpha": alpha,
            "delta_eta": delta_eta,
            "delta_LTT": delta_ltt,
            "K": K,
            "c_human": c_human,
            "c_llm": c_llm,
            "normalize_base_scores": config.normalize_base_scores,
        },
```

- [ ] **Step 5: Run the integration test to confirm it passes**

```bash
python3 -m pytest "cascade_rc/tests/test_main_calibrate_synthetic.py::test_calibrate_config_snapshot_contains_normalize_flag" \
    -v 2>&1 | tail -10
```

Expected: `1 passed`.

- [ ] **Step 6: Run the full score normalizer test suite to confirm no regression**

```bash
python3 -m pytest cascade_rc/tests/test_score_normalizer.py -v 2>&1 | tail -5
```

Expected: `10 passed`.

- [ ] **Step 7: Commit**

```bash
git add cascade_rc/calibration/main_calibrate.py cascade_rc/tests/test_main_calibrate_synthetic.py
git commit -m "feat(calibrate): inject minmax_scale_s at parquet load; add flag to config_snapshot"
```

---

## Task 4: Inject scaling in `budget_split._run_topic()`

**Files:**
- Modify: `cascade_rc/ablations/budget_split.py`
- Modify: `cascade_rc/tests/test_budget_split.py`

- [ ] **Step 1: Write the failing mock-based test**

Open `cascade_rc/tests/test_budget_split.py` and **append** the following test block (do not replace existing content):

```python
# ---------------------------------------------------------------------------
# test_run_topic_passes_scaled_df_to_compute_wss
# ---------------------------------------------------------------------------

def test_run_topic_passes_scaled_df_to_compute_wss(tmp_path):
    """_run_topic() with normalize_base_scores=True passes s ∈ [0,1] df to _compute_wss."""
    import sys
    import numpy as np
    import pandas as pd
    import pytest
    from pathlib import Path
    from unittest.mock import patch, MagicMock

    _root = Path(__file__).parent.parent.parent.resolve()
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    from cascade_rc.ablations.budget_split import _run_topic
    from cascade_rc.config import CascadeRCConfig, LTTBudget

    # Build synthetic parquet with squashed s ∈ [0.011, 0.032]
    rng = np.random.default_rng(7)
    n = 300
    is_split = np.array([0] * 60 + [1] * 150 + [2] * 90, dtype=np.int8)
    y = np.zeros(n, dtype=np.int64)
    y[:12] = 1; y[60:90] = 1; y[210:228] = 1
    df_raw = pd.DataFrame({
        "pmid": [str(i) for i in range(n)],
        "s": rng.uniform(0.011, 0.032, n),
        "u": rng.uniform(0.0, 1.0, n),
        "y_abstract": y,
        "llm_y_hat": rng.integers(0, 2, n, dtype=np.int64),
        "is_split": is_split,
        "is_calib": np.where(np.array([0]*60+[1]*150+[2]*90) == 1, 1, 0),
    })
    parquet_path = tmp_path / "CD_test.parquet"
    df_raw.to_parquet(parquet_path, index=False)

    # Build a fake CertificationResult with theta_hat in [0,1] scaled space
    mock_result = MagicMock()
    mock_result.theta_hat = np.array([0.3, 0.7, 0.5])
    mock_result.lambda_hat_mask = np.array([True, False])
    mock_result.theta_grid = np.array([[0.3, 0.7, 0.5], [0.0, 0.0, 0.0]])
    mock_result.slack_mat = np.zeros((2, 30))
    mock_result.eta_lcb_grid = np.zeros(2)
    mock_result.alpha_dagger_grid = np.zeros(2)
    mock_result.m_plus = 30

    captured = {}

    def fake_compute_wss(result, df_full):
        captured["df"] = df_full
        return {"wss": 0.5, "status": "ok", "achieved_recall": 0.95}

    cfg = CascadeRCConfig(
        normalize_base_scores=True,
        n_jobs_calib=1,
        ltt=LTTBudget(
            alpha=0.10, delta_total=0.10, delta_eta=0.03, delta_LTT=0.07,
            K=3, B=3, ensemble_temperature=0.7, c_human=5.0, c_llm=0.001,
            delta_bootstrap=0.05,
        ),
    )

    with patch("cascade_rc.calibration.main_calibrate.calibrate", return_value=mock_result):
        with patch("cascade_rc.ablations.budget_split._compute_wss", side_effect=fake_compute_wss):
            _run_topic(
                topic_id="CD_test",
                parquet_path=parquet_path,
                delta_eta=0.03,
                delta_ltt=0.07,
                config=cfg,
                out_dir=tmp_path,
            )

    assert "df" in captured, "_compute_wss was never called"
    s_max = float(captured["df"]["s"].max())
    s_min = float(captured["df"]["s"].min())
    assert s_max == pytest.approx(1.0, abs=1e-9), (
        f"Expected s.max()=1.0 after scaling, got {s_max}"
    )
    assert s_min == pytest.approx(0.0, abs=1e-9), (
        f"Expected s.min()=0.0 after scaling, got {s_min}"
    )
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
python3 -m pytest "cascade_rc/tests/test_budget_split.py::test_run_topic_passes_scaled_df_to_compute_wss" \
    -v 2>&1 | tail -10
```

Expected: `AssertionError: Expected s.max()=1.0 after scaling` (df is still in squashed range [0.011, 0.032]).

- [ ] **Step 3: Inject scaling in `_run_topic()`**

In `cascade_rc/ablations/budget_split.py`, locate `df = pd.read_parquet(parquet_path)` (line 98). Replace it with:

```python
    df = pd.read_parquet(parquet_path)
    if config.normalize_base_scores:
        from cascade_rc.data.score_normalizer import minmax_scale_s
        df = minmax_scale_s(df)
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
python3 -m pytest "cascade_rc/tests/test_budget_split.py::test_run_topic_passes_scaled_df_to_compute_wss" \
    -v 2>&1 | tail -8
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/ablations/budget_split.py cascade_rc/tests/test_budget_split.py
git commit -m "feat(budget_split): inject minmax_scale_s in _run_topic() for WSS coordinate consistency"
```

---

## Task 5: Full regression check

- [ ] **Step 1: Run the complete test suite**

```bash
python3 -m pytest cascade_rc/tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all previously passing tests still pass; 0 new failures.

- [ ] **Step 2: Verify `normalize_base_scores=False` is the default and changes nothing**

```bash
python3 -c "
from cascade_rc.config import CascadeRCConfig
c = CascadeRCConfig()
assert c.normalize_base_scores is False
print('OK: normalize_base_scores defaults to False')
"
```

Expected: `OK: normalize_base_scores defaults to False`

- [ ] **Step 3: Commit**

If there are any test-fixing commits from Step 1, commit them now. Otherwise just confirm the branch is clean:

```bash
git status
```

Expected: `nothing to commit, working tree clean`

---

## Self-review against spec

| Spec requirement | Covered by |
|-----------------|-----------|
| `normalize_base_scores: bool = False` in `CascadeRCConfig` | Task 2, Step 3 |
| `minmax_scale_s()` in `score_normalizer.py` with debug logging | Task 1, Step 3 |
| Injection in `calibrate()` after parquet load | Task 3, Step 3 |
| `normalize_base_scores` in `config_snapshot` | Task 3, Step 4 |
| Injection in `budget_split._run_topic()` for WSS coordinate consistency | Task 4, Step 3 |
| Global min/max from full df (never per-split) | Enforced by injecting before any split filtering |
| `alpha_sweep.py` coverage | Covered via `calibrate()` Site 1 (no third site needed) |
| Idempotency on already-`[0,1]` data | Task 1, `test_minmax_scale_s_idempotent` |
| No-op on constant-score input | Task 1, `test_minmax_scale_s_constant_noop` |
| Rank preservation | Task 1, `test_minmax_scale_s_squashed_range` (Spearman check) |
| Default `False` preserves existing behavior | Task 5, Step 2 |
