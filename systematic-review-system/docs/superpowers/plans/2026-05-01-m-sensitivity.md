# m₊ Sensitivity Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `cascade_rc/ablations/m_sensitivity.py` — a sweep of m₊ ∈ {26,35,50,75,100,full} per topic that calls the existing `calibrate()`, measures WSS@95/mean η̂⁻⋆/abstention, and writes a tidy parquet + per-topic plots.

**Architecture:** Temp-file subsampling (no changes to `calibrate()` signature); joblib loky parallelism over topics; `_subsample_to_m` derives a per-topic permutation (no `m` in seed hash) so smaller grids are nested prefixes of larger ones. Topics with `m_plus_full < N_min` are skipped entirely before calibration and recorded in `skipped_topics.json`.

**Tech Stack:** Python 3.11, pandas, numpy, joblib, matplotlib, pytest, existing `cascade_rc.calibration.main_calibrate.calibrate`, `cascade_rc.evaluation.metrics.wss_at_recall`, `cascade_rc.synthetic.beta_mixture.generate_paper_running_example`.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `cascade_rc/ablations/__init__.py` | Package marker |
| Create | `cascade_rc/ablations/m_sensitivity.py` | All sweep logic + CLI |
| Create | `cascade_rc/tests/test_m_sensitivity.py` | Four acceptance tests |

---

### Task 1: Package scaffold, schema constants, and dry-run path

**Files:**
- Create: `cascade_rc/ablations/__init__.py`
- Create: `cascade_rc/ablations/m_sensitivity.py` (skeleton: schema + `_empty_dataframe` + `run_sweep` dry-run only)
- Create: `cascade_rc/tests/test_m_sensitivity.py` (`test_dry_run_schema` only)

- [ ] **Step 1: Write the failing test**

```python
# cascade_rc/tests/test_m_sensitivity.py
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cascade_rc.synthetic.beta_mixture import generate_paper_running_example


def _make_synthetic_parquet(
    tmp_path: Path,
    n: int = 1_000,
    seed: int = 0,
    n_calib_pos: int | None = None,
    filename: str = "TOPIC_A.parquet",
) -> Path:
    """Write a synthetic enriched parquet to tmp_path and return its path."""
    df = generate_paper_running_example(n=n, seed=seed)
    df = df.rename(columns={"y": "y_abstract"})

    if n_calib_pos is not None:
        pos_idx = df.index[df["y_abstract"] == 1].tolist()
        neg_idx = df.index[df["y_abstract"] == 0].tolist()
        is_calib = np.zeros(len(df), dtype=int)
        for i in pos_idx[:n_calib_pos]:
            is_calib[i] = 1
        for i in neg_idx[:200]:
            is_calib[i] = 1
        df["is_calib"] = is_calib
    else:
        rng = np.random.default_rng(20260429)
        is_calib = np.zeros(len(df), dtype=int)
        for label in [0, 1]:
            idx = df.index[df["y_abstract"] == label].tolist()
            calib_idx = rng.choice(idx, size=len(idx) // 2, replace=False)
            is_calib[calib_idx] = 1
        df["is_calib"] = is_calib

    path = tmp_path / filename
    df.to_parquet(path, index=False)
    return path


def test_dry_run_schema(tmp_path: Path) -> None:
    """--dry-run writes a zero-row parquet with exactly the expected schema."""
    from cascade_rc.ablations.m_sensitivity import run_sweep, PARQUET_SCHEMA

    run_sweep(data_dir=tmp_path, out_dir=tmp_path / "out", seed=42, dry_run=True)

    parquet_path = tmp_path / "out" / "m_sensitivity.parquet"
    assert parquet_path.exists(), "m_sensitivity.parquet not created"

    df = pd.read_parquet(parquet_path)
    assert len(df) == 0, f"Expected 0 rows, got {len(df)}"
    assert list(df.columns) == list(PARQUET_SCHEMA.keys()), (
        f"Column mismatch: {list(df.columns)} != {list(PARQUET_SCHEMA.keys())}"
    )
    for col, expected_dtype in PARQUET_SCHEMA.items():
        assert str(df[col].dtype) == str(expected_dtype), (
            f"Column '{col}': expected dtype '{expected_dtype}', got '{df[col].dtype}'"
        )

    skipped_path = tmp_path / "out" / "skipped_topics.json"
    assert skipped_path.exists(), "skipped_topics.json not created"
    assert json.loads(skipped_path.read_text()) == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_dry_run_schema -v
```

Expected: `ModuleNotFoundError: No module named 'cascade_rc.ablations'`

- [ ] **Step 3: Create the ablations package and skeleton module**

```python
# cascade_rc/ablations/__init__.py
```
(empty file — just marks the package)

```python
# cascade_rc/ablations/m_sensitivity.py
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

M_GRID_CANDIDATES: list[int] = [26, 35, 50, 75, 100]

PARQUET_SCHEMA: dict[str, str] = {
    "topic_id": "object",
    "m_target": "int64",
    "m_actual": "int64",
    "abstention": "bool",
    "wss_95": "float64",
    "wss_status": "object",
    "achieved_recall": "float64",
    "mean_eta_lcb": "float64",
}


def _empty_dataframe() -> pd.DataFrame:
    """Return a zero-row DataFrame matching PARQUET_SCHEMA."""
    return pd.DataFrame(
        {col: pd.Series(dtype=dtype) for col, dtype in PARQUET_SCHEMA.items()}
    )


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    seed: int = 42,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run m-sensitivity sweep over all topics in data_dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "m_sensitivity.parquet", index=False)
        (out_dir / "skipped_topics.json").write_text(json.dumps([]))
        return df_empty

    raise NotImplementedError("Non-dry-run sweep not yet implemented")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_dry_run_schema -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/ablations/__init__.py cascade_rc/ablations/m_sensitivity.py cascade_rc/tests/test_m_sensitivity.py
git commit -m "feat(ablations): scaffold m_sensitivity package with dry-run schema"
```

---

### Task 2: Subsampling helper and m-grid

**Files:**
- Modify: `cascade_rc/ablations/m_sensitivity.py` — add `_compute_m_grid`, `_subsample_to_m`
- Modify: `cascade_rc/tests/test_m_sensitivity.py` — add `test_nested_subsamples`

- [ ] **Step 1: Write the failing test**

Append to `cascade_rc/tests/test_m_sensitivity.py`:

```python
def test_nested_subsamples(tmp_path: Path) -> None:
    """m=26 subsample is a strict prefix of m=50 (nested-seed property).

    Both calls use the same (topic_id, global_seed) pair; m is intentionally
    excluded from the hash. permuted[:26] must be a subset of permuted[:50].
    Do NOT add m to the hash — that would break this guarantee.
    """
    from cascade_rc.ablations.m_sensitivity import _subsample_to_m

    parquet_path = _make_synthetic_parquet(tmp_path, n=5_000, seed=1)
    df = pd.read_parquet(parquet_path)

    m_plus = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())
    assert m_plus >= 50, f"Not enough cal positives for test: {m_plus}"

    df_26 = _subsample_to_m(df, 26, "TOPIC_A", global_seed=42)
    df_50 = _subsample_to_m(df, 50, "TOPIC_A", global_seed=42)

    kept_26 = set(
        df_26.index[(df_26["is_calib"] == 1) & (df_26["y_abstract"] == 1)].tolist()
    )
    kept_50 = set(
        df_50.index[(df_50["is_calib"] == 1) & (df_50["y_abstract"] == 1)].tolist()
    )

    assert len(kept_26) == 26, f"Expected 26 cal positives, got {len(kept_26)}"
    assert len(kept_50) == 50, f"Expected 50 cal positives, got {len(kept_50)}"
    assert kept_26.issubset(kept_50), (
        "m=26 kept indices must be a strict subset of m=50 kept indices. "
        "Nested-seed guarantee requires m to be excluded from the hash."
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_nested_subsamples -v
```

Expected: `ImportError: cannot import name '_subsample_to_m'`

- [ ] **Step 3: Add `_compute_m_grid` and `_subsample_to_m` to `m_sensitivity.py`**

Add after `_empty_dataframe` in `cascade_rc/ablations/m_sensitivity.py`:

```python
import numpy as np


def _compute_m_grid(m_plus_full: int, n_min: int) -> list[int]:
    """Return sorted unique m values to sweep, all <= m_plus_full.

    Always includes m_plus_full itself ("full" entry). Excludes candidates
    above m_plus_full. Deduplicates in case m_plus_full equals a candidate.
    """
    grid = [m for m in M_GRID_CANDIDATES if m <= m_plus_full]
    if m_plus_full not in grid:
        grid.append(m_plus_full)
    return sorted(set(grid))


def _subsample_to_m(
    df: pd.DataFrame,
    m: int,
    topic_id: str,
    global_seed: int,
) -> pd.DataFrame:
    """Return df with calibration positives subsampled to exactly m rows.

    Seed is derived from (topic_id, global_seed) only — NOT m — so that
    smaller m values are strict prefixes of larger ones (nested subsets).
    Unsampled calibration positives are dropped entirely; test rows
    (is_calib==0) are untouched, keeping the test split constant.
    """
    cal_pos_mask = (df["is_calib"] == 1) & (df["y_abstract"] == 1)
    cal_pos_indices = df.index[cal_pos_mask].to_numpy()

    if len(cal_pos_indices) <= m:
        return df.copy()

    rng = np.random.default_rng(hash((topic_id, global_seed)) & 0xFFFFFFFF)
    permuted = rng.permutation(cal_pos_indices)
    drop_indices = permuted[m:]
    return df.drop(index=drop_indices).copy()
```

Also add `import numpy as np` at the top of `m_sensitivity.py`.

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_nested_subsamples -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/ablations/m_sensitivity.py cascade_rc/tests/test_m_sensitivity.py
git commit -m "feat(ablations): add _compute_m_grid and _subsample_to_m with nested-seed guarantee"
```

---

### Task 3: WSS routing helper

**Files:**
- Modify: `cascade_rc/ablations/m_sensitivity.py` — add `_compute_wss`
- Modify: `cascade_rc/tests/test_m_sensitivity.py` — add `test_wss_routed_correctly`

- [ ] **Step 1: Write the failing test**

Append to `cascade_rc/tests/test_m_sensitivity.py`:

```python
def test_wss_routed_correctly() -> None:
    """_compute_wss applies auto_reject = (s < lambda_lo) to test split only.

    Setup: 3 test docs with y=[1,1,0] and s=[0.3, 0.6, 0.1].
    theta_hat = (lambda_lo=0.5, lambda_hi=1.0, tau_se=0.5).
    auto_reject = s < 0.5 → [True, False, True].
    predictions = [0, 1, 0].
    Positives captured: index 1 only (s=0.6) → recall = 1/2 = 0.5 < 0.95.
    Expected: status='recall_target_missed', achieved_recall=0.5.
    """
    from cascade_rc.ablations.m_sensitivity import _compute_wss
    from cascade_rc.certificates.store import CertificationResult

    df = pd.DataFrame({
        "is_calib": [0, 0, 0, 1, 1],
        "y_abstract": [1, 1, 0, 1, 0],
        "s":          [0.3, 0.6, 0.1, 0.9, 0.2],
        "u":          [0.5, 0.5, 0.5, 0.5, 0.5],
        "llm_y_hat":  [1, 1, 0, 1, 0],
    })

    result = CertificationResult(
        topic="T",
        status="certified",
        abstain_reason=None,
        m_plus=1,
        theta_hat=np.array([0.5, 1.0, 0.5]),
        lambda_hat_mask=np.ones(1, dtype=bool),
        theta_grid=np.array([[0.5, 1.0, 0.5]]),
        eta_lcb_grid=np.array([0.1]),
        r_hat_grid=np.array([0.1]),
        p_hb_grid=np.array([0.01]),
        alpha_dagger_grid=np.array([0.2]),
        slack_mat=np.zeros((1, 1)),
        config_snapshot={},
        timestamp="2026-05-01T00:00:00+00:00",
    )

    wss_dict = _compute_wss(result, df)
    assert wss_dict["status"] == "recall_target_missed", (
        f"Expected 'recall_target_missed', got '{wss_dict['status']}'"
    )
    assert abs(wss_dict["achieved_recall"] - 0.5) < 1e-9, (
        f"Expected achieved_recall=0.5, got {wss_dict['achieved_recall']}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_wss_routed_correctly -v
```

Expected: `ImportError: cannot import name '_compute_wss'`

- [ ] **Step 3: Add `_compute_wss` to `m_sensitivity.py`**

Add after `_subsample_to_m` in `cascade_rc/ablations/m_sensitivity.py`:

```python
from cascade_rc.certificates.store import CertificationResult
from cascade_rc.evaluation.metrics import wss_at_recall


def _compute_wss(result: CertificationResult, df_full: pd.DataFrame) -> dict:
    """Compute WSS@95 on the test split (is_calib==0) under certified theta_hat.

    Routing: documents with s < lambda_lo are auto-rejected (predictions=0).
    Everything else reaches the working set (predictions=1), which includes
    auto-accepted, SE-escalated, and uncertain-but-no-SE documents.
    Auto-rejected positives are false negatives — wss_at_recall captures
    this as status='recall_target_missed' when achieved recall < 0.95.
    """
    df_test = df_full[df_full["is_calib"] == 0]
    s = df_test["s"].to_numpy(dtype=np.float64)
    y = df_test["y_abstract"].to_numpy(dtype=np.int64)

    lam_lo = float(result.theta_hat[0])
    auto_reject = s < lam_lo
    predictions = (~auto_reject).astype(int)

    return wss_at_recall(predictions, y, target_recall=0.95)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_wss_routed_correctly -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/ablations/m_sensitivity.py cascade_rc/tests/test_m_sensitivity.py
git commit -m "feat(ablations): add _compute_wss routing helper"
```

---

### Task 4: Per-topic runner with topic skip guard

**Files:**
- Modify: `cascade_rc/ablations/m_sensitivity.py` — add `_run_topic`
- Modify: `cascade_rc/tests/test_m_sensitivity.py` — add `test_skip_low_prevalence_topic`

- [ ] **Step 1: Write the failing test**

Append to `cascade_rc/tests/test_m_sensitivity.py`:

```python
def test_skip_low_prevalence_topic(tmp_path: Path) -> None:
    """Topic with m_plus_full < N_min produces zero rows and appears in skipped_topics.json.

    N_min = ceil(ln(1/0.07) / (-ln(0.9))) = 26 with default LTTBudget.
    We create a topic with only 5 calibration positives. The sweep must skip
    it entirely — no calibrate() call — and record it in skipped_topics.json.
    """
    from cascade_rc.ablations.m_sensitivity import run_sweep

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_synthetic_parquet(
        data_dir, n=1_000, seed=7, n_calib_pos=5, filename="LOW_PREV.parquet"
    )

    out_dir = tmp_path / "out"
    df = run_sweep(data_dir=data_dir, out_dir=out_dir, seed=42)

    assert len(df) == 0, f"Expected 0 rows for skipped topic, got {len(df)}"

    skipped = json.loads((out_dir / "skipped_topics.json").read_text())
    assert "LOW_PREV" in skipped, f"LOW_PREV not in skipped_topics.json: {skipped}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_skip_low_prevalence_topic -v
```

Expected: `NotImplementedError: Non-dry-run sweep not yet implemented`

- [ ] **Step 3: Add `_run_topic` to `m_sensitivity.py`**

Add these imports at the top of `m_sensitivity.py`:

```python
import math
import tempfile

from cascade_rc.calibration.main_calibrate import calibrate, _compute_n_min
from cascade_rc.config import CascadeRCConfig
```

Add the `_run_topic` function after `_compute_wss`:

```python
def _run_topic(
    topic_id: str,
    parquet_path: Path,
    config: CascadeRCConfig,
    global_seed: int,
    out_dir: Path,
) -> tuple[list[dict], bool]:
    """Run m-sensitivity sweep for one topic.

    Returns:
        (rows, skipped): rows is a list of result-row dicts (one per m-cell);
        skipped=True if the topic was skipped due to m_plus_full < N_min.
    """
    df = pd.read_parquet(parquet_path)
    m_plus_full = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())
    n_min = _compute_n_min(config.ltt.alpha, config.ltt.delta_LTT)

    if m_plus_full < n_min:
        return [], True

    m_grid = _compute_m_grid(m_plus_full, n_min)
    rows: list[dict] = []
    cache_dir = out_dir / "calibration_cache"

    for m in m_grid:
        artefact_dir = cache_dir / f"{topic_id}_m{m}"
        artefact_dir.mkdir(parents=True, exist_ok=True)

        tmp_parquet: Path | None = None
        if m == m_plus_full:
            calib_path = parquet_path
        else:
            df_sub = _subsample_to_m(df, m, topic_id, global_seed)
            with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
                tmp_parquet = Path(f.name)
            df_sub.to_parquet(tmp_parquet, index=False)
            calib_path = tmp_parquet

        try:
            result = calibrate(
                topic_id, calib_path, config, artefact_dir=artefact_dir
            )
        finally:
            if tmp_parquet is not None and tmp_parquet.exists():
                tmp_parquet.unlink(missing_ok=True)

        if isinstance(result, tuple):
            rows.append({
                "topic_id": topic_id,
                "m_target": m,
                "m_actual": m,
                "abstention": True,
                "wss_95": float("nan"),
                "wss_status": "abstained",
                "achieved_recall": float("nan"),
                "mean_eta_lcb": float("nan"),
            })
        else:
            wss_dict = _compute_wss(result, df)
            rows.append({
                "topic_id": topic_id,
                "m_target": m,
                "m_actual": m,
                "abstention": False,
                "wss_95": wss_dict["wss"],
                "wss_status": wss_dict["status"],
                "achieved_recall": wss_dict["achieved_recall"],
                "mean_eta_lcb": float(np.mean(result.eta_lcb_grid)),
            })

    return rows, False
```

- [ ] **Step 4: Update `run_sweep` to call `_run_topic` via joblib**

Replace the `raise NotImplementedError` block in `run_sweep` with:

```python
    from joblib import Parallel, delayed

    config = CascadeRCConfig()
    parquet_paths = sorted(Path(data_dir).glob("*.parquet"))
    if topics_filter:
        parquet_paths = [p for p in parquet_paths if p.stem in topics_filter]

    results: list[tuple[list[dict], bool]] = Parallel(
        n_jobs=n_jobs, backend="loky"
    )(
        delayed(_run_topic)(p.stem, p, config, seed, out_dir)
        for p in parquet_paths
    )

    all_rows: list[dict] = []
    skipped_topics: list[str] = []
    for (rows, skipped), p in zip(results, parquet_paths):
        all_rows.extend(rows)
        if skipped:
            skipped_topics.append(p.stem)

    if all_rows:
        df = pd.DataFrame(all_rows).astype(PARQUET_SCHEMA)
    else:
        df = _empty_dataframe()

    df.to_parquet(out_dir / "m_sensitivity.parquet", index=False)
    (out_dir / "skipped_topics.json").write_text(json.dumps(sorted(skipped_topics)))
    return df
```

- [ ] **Step 5: Run test to verify it passes**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_skip_low_prevalence_topic -v
```

Expected: `PASSED` (topic skipped before any calibrate() call)

- [ ] **Step 6: Run all four tests to confirm no regressions**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py -v
```

Expected: 3 tests pass (`test_dry_run_schema`, `test_nested_subsamples`, `test_skip_low_prevalence_topic`, `test_wss_routed_correctly`)

- [ ] **Step 7: Commit**

```bash
git add cascade_rc/ablations/m_sensitivity.py cascade_rc/tests/test_m_sensitivity.py
git commit -m "feat(ablations): add _run_topic with skip guard and joblib sweep integration"
```

---

### Task 5: Plots — per-topic and overview figures

**Files:**
- Modify: `cascade_rc/ablations/m_sensitivity.py` — add `_plot_topic`, `_plot_overview`, wire into `run_sweep`

- [ ] **Step 1: Add `_plot_topic` and `_plot_overview` to `m_sensitivity.py`**

Add after `_run_topic`:

```python
def _plot_topic(df_topic: pd.DataFrame, out_dir: Path, topic_id: str) -> None:
    """Save 3-panel figure for one topic: WSS@95 / mean η̂⁻⋆ / abstention."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    m = df_topic["m_actual"].to_numpy()
    wss = df_topic["wss_95"].to_numpy(dtype=float)
    eta = df_topic["mean_eta_lcb"].to_numpy(dtype=float)
    abstention = df_topic["abstention"].to_numpy().astype(int)
    status = df_topic["wss_status"].to_numpy()

    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(6, 8))

    ok_mask = status == "ok"
    missed_mask = status == "recall_target_missed"
    if ok_mask.any():
        axes[0].plot(m[ok_mask], wss[ok_mask], "bo-", label="ok")
    if missed_mask.any():
        axes[0].plot(m[missed_mask], np.zeros(missed_mask.sum()), "rx",
                     markersize=10, label="recall missed")
    axes[0].set_ylabel("WSS@95")
    axes[0].set_title(topic_id)
    axes[0].legend(fontsize=8)

    non_abstained = ~df_topic["abstention"].to_numpy()
    if non_abstained.any():
        axes[1].plot(m[non_abstained], eta[non_abstained], "go-")
    axes[1].set_ylabel("mean η̂⁻⋆")

    axes[2].step(m, abstention, where="mid", color="red")
    axes[2].set_ylabel("abstention")
    axes[2].set_yticks([0, 1])
    axes[2].set_xlabel("m_actual (positives in calibration)")

    plt.tight_layout()
    fig.savefig(
        plot_dir / f"m_sensitivity_{topic_id}.png", dpi=150, bbox_inches="tight"
    )
    plt.close(fig)


def _plot_overview(df: pd.DataFrame, out_dir: Path) -> None:
    """Save combined 3-panel figure: all topics faded + bold median lines."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(8, 10))

    for topic_id in df["topic_id"].unique():
        df_t = df[df["topic_id"] == topic_id]
        m = df_t["m_actual"].to_numpy()
        axes[0].plot(m, df_t["wss_95"].to_numpy(dtype=float), "b-",
                     alpha=0.3, linewidth=1)
        axes[1].plot(m, df_t["mean_eta_lcb"].to_numpy(dtype=float), "g-",
                     alpha=0.3, linewidth=1)
        axes[2].step(m, df_t["abstention"].to_numpy().astype(int),
                     where="mid", alpha=0.3, linewidth=1)

    for ax, col in zip(axes[:2], ["wss_95", "mean_eta_lcb"]):
        pivot = df.groupby("m_actual")[col].median()
        ax.plot(pivot.index, pivot.values, "k-", linewidth=2.5, label="median")
        ax.legend(fontsize=8)

    axes[0].set_ylabel("WSS@95")
    axes[1].set_ylabel("mean η̂⁻⋆")
    axes[2].set_ylabel("abstention indicator")
    axes[2].set_xlabel("m_actual (positives in calibration)")

    plt.tight_layout()
    fig.savefig(
        plot_dir / "m_sensitivity_overview.png", dpi=150, bbox_inches="tight"
    )
    plt.close(fig)
```

- [ ] **Step 2: Wire plots into `run_sweep` — add after `return df` line is reached**

After `(out_dir / "skipped_topics.json").write_text(...)` and before `return df` in `run_sweep`, add:

```python
    if not df.empty:
        for tid in df["topic_id"].unique():
            _plot_topic(df[df["topic_id"] == tid], out_dir, tid)
        if df["topic_id"].nunique() > 1:
            _plot_overview(df, out_dir)
```

- [ ] **Step 3: Verify dry-run still works (plots must NOT be created)**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py::test_dry_run_schema -v
```

Expected: `PASSED` — dry_run returns before any plot code is reached.

- [ ] **Step 4: Run all tests**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py -v
```

Expected: all 4 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/ablations/m_sensitivity.py
git commit -m "feat(ablations): add per-topic and overview m-sensitivity plots"
```

---

### Task 6: CLI entry point and end-to-end dry-run verification

**Files:**
- Modify: `cascade_rc/ablations/m_sensitivity.py` — add `main()` and `__main__` guard

- [ ] **Step 1: Add `main()` to `m_sensitivity.py`**

Append to `cascade_rc/ablations/m_sensitivity.py`:

```python
def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="m₊ sensitivity sweep for CASCADE-RC",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir", type=Path,
        default=Path("artefacts/cascade_rc/data"),
        help="Directory containing enriched topic parquets",
    )
    parser.add_argument(
        "--out-dir", type=Path,
        default=Path("artefacts/cascade_rc/ablations"),
        help="Output directory for parquet, JSON, and plots",
    )
    parser.add_argument("--seed", type=int, default=42, help="Global RNG seed")
    parser.add_argument(
        "--topics", nargs="+", default=None,
        help="Restrict sweep to these topic IDs (space-separated)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Write schema-only parquet without running calibration",
    )
    parser.add_argument(
        "--n-jobs", type=int, default=1,
        help="Parallel topic workers (loky backend)",
    )
    args = parser.parse_args()

    df = run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        seed=args.seed,
        topics_filter=args.topics,
        n_jobs=args.n_jobs,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(
            f"DRY-RUN: schema written to {args.out_dir / 'm_sensitivity.parquet'}"
        )
    else:
        print(
            f"Sweep complete: {len(df)} rows, "
            f"{df['topic_id'].nunique()} topics"
        )
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify `--dry-run` CLI end-to-end**

```bash
cd systematic-review-system
python -m cascade_rc.ablations.m_sensitivity \
    --data-dir /tmp/empty_dir \
    --out-dir /tmp/m_sens_test \
    --dry-run
```

Create `/tmp/empty_dir` first if it doesn't exist: `mkdir -p /tmp/empty_dir`

Expected output:
```
DRY-RUN: schema written to /tmp/m_sens_test/m_sensitivity.parquet
```

Verify the parquet:
```bash
python -c "
import pandas as pd, json
df = pd.read_parquet('/tmp/m_sens_test/m_sensitivity.parquet')
print('columns:', list(df.columns))
print('rows:', len(df))
print('skipped:', json.loads(open('/tmp/m_sens_test/skipped_topics.json').read()))
"
```

Expected:
```
columns: ['topic_id', 'm_target', 'm_actual', 'abstention', 'wss_95', 'wss_status', 'achieved_recall', 'mean_eta_lcb']
rows: 0
skipped: []
```

- [ ] **Step 3: Run the full test suite for m_sensitivity**

```bash
python -m pytest cascade_rc/tests/test_m_sensitivity.py -v
```

Expected: all 4 tests `PASSED`

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/ablations/m_sensitivity.py
git commit -m "feat(ablations): add CLI entry point for m-sensitivity sweep"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by task |
|---|---|
| Sweep m₊ ∈ {26,35,50,75,100,full}, only ≤ m_plus_full | Task 2 `_compute_m_grid` |
| Respect N_min — skip topics where m_plus_full < N_min | Task 4 `_run_topic` skip guard |
| Nested subsamples (smaller m is prefix of larger m) | Task 2 `_subsample_to_m`, tested in Task 2 |
| Unsampled calibration positives dropped (not reassigned) | Task 2 `_subsample_to_m` (drop_indices) |
| Fast path when m == m_plus_full (no temp file) | Task 4 `_run_topic` |
| Output parquet with 8 columns and correct dtypes | Task 1 `PARQUET_SCHEMA`, Task 4 `run_sweep` |
| `wss_status`, `achieved_recall` columns | Task 3 `_compute_wss`, Task 1 schema |
| `skipped_topics.json` written once at end of sweep | Task 4 `run_sweep` |
| `--dry-run` produces schema without calibration | Task 1, Task 6 |
| WSS@95 via `wss_at_recall` (Cohen 2006, not screening rate) | Task 3 `_compute_wss` |
| `auto_reject = s < lambda_lo`, rest in working set | Task 3 `_compute_wss` |
| Per-topic 3-subplot figure (WSS/η̂/abstention) | Task 5 `_plot_topic` |
| `wss_status="ok"` → blue ○, `"recall_target_missed"` → red ✗ | Task 5 `_plot_topic` |
| Combined overview figure with median lines | Task 5 `_plot_overview` |
| `joblib Parallel(backend="loky")` | Task 4 `run_sweep` |
| CLI flags `--data-dir --out-dir --seed --topics --dry-run --n-jobs` | Task 6 `main()` |
| `test_dry_run_schema` | Task 1 |
| `test_nested_subsamples` | Task 2 |
| `test_skip_low_prevalence_topic` | Task 4 |
| `test_wss_routed_correctly` | Task 3 |
