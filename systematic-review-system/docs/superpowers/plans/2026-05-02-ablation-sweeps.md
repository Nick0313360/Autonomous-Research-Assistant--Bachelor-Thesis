# Ablation Sweeps (Prompt 10.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two ablation sweep modules — `budget_split.py` and `walk_ordering.py` — that sweep (δ_η, δ_LTT) budget splits and walk-ordering strategies across the three headline DTA topics, emitting parquets and plots for Phase 12 figures.

**Architecture:** Two new modules follow the `m_sensitivity.py` template exactly: `_run_topic()` worker calls `calibrate()` in-process, `run_sweep()` dispatches via `joblib.Parallel(backend="loky")`, parquet + plots are written to `artefacts/cascade_rc/ablations/`. Two small prerequisite changes first: (1) fix the `LTTBudget` validator to use `math.isclose`, and (2) add an `order_fn: Callable | None = None` param to `calibrate()`. Walk-ordering workers reconstruct the callable from `(order_name, order_seed)` **inside** `_run_topic` — never passed across the process boundary — because lambdas fail pickle under `loky`.

**Tech Stack:** Python 3.11, pydantic 2.x, numpy 1.26.4, pandas 2.2.2, matplotlib 3.9.0, joblib 1.4.2, pytest 8.2.2

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `cascade_rc/config.py` | Modify | Fix `_check_delta_split` to use `math.isclose` |
| `cascade_rc/calibration/main_calibrate.py` | Modify | Add `order_fn` param; update imports |
| `cascade_rc/ablations/budget_split.py` | **Create** | Budget-split ablation: 5 splits × 3 topics |
| `cascade_rc/ablations/walk_ordering.py` | **Create** | Walk-ordering ablation: 8 variants × 3 topics |
| `cascade_rc/tests/test_budget_split.py` | **Create** | Tests for budget_split module |
| `cascade_rc/tests/test_walk_ordering.py` | **Create** | Tests for walk_ordering module |

---

## Task 1: Fix `LTTBudget` validator

**Files:**
- Modify: `cascade_rc/config.py`
- Create: `cascade_rc/tests/test_budget_split.py`

- [ ] **Step 1: Create test file with validator tests**

Create `cascade_rc/tests/test_budget_split.py`:

```python
from __future__ import annotations

import math

import pytest

from cascade_rc.config import LTTBudget


@pytest.mark.parametrize("delta_eta,delta_ltt", [
    (0.01, 0.09),
    (0.03, 0.07),
    (0.05, 0.05),
    (0.07, 0.03),
    (0.09, 0.01),
])
def test_ltt_budget_ablation_pairs_are_valid(delta_eta: float, delta_ltt: float) -> None:
    """All 5 (δ_η, δ_LTT) ablation pairs must construct LTTBudget without error."""
    ltt = LTTBudget(
        alpha=0.10,
        delta_total=0.10,
        delta_eta=delta_eta,
        delta_LTT=delta_ltt,
        K=20,
    )
    assert math.isclose(ltt.delta_eta + ltt.delta_LTT, ltt.delta_total, abs_tol=1e-9)


def test_ltt_budget_validator_rejects_invalid_split() -> None:
    """Validator must raise ValueError when delta_eta + delta_LTT != delta_total."""
    with pytest.raises(ValueError, match="delta_eta"):
        LTTBudget(delta_eta=0.05, delta_LTT=0.05, delta_total=0.20)
```

- [ ] **Step 2: Run tests (expect PASS — documents current correct behavior)**

```
pytest cascade_rc/tests/test_budget_split.py -v
```

Expected: 6 PASS.

- [ ] **Step 3: Fix validator in `cascade_rc/config.py`**

Add `import math` at the top of the file (after `from __future__ import annotations`).

Replace the `_check_delta_split` method body:

```python
@model_validator(mode="after")
def _check_delta_split(self) -> "LTTBudget":
    if not math.isclose(self.delta_eta + self.delta_LTT, self.delta_total, abs_tol=1e-9):
        raise ValueError(
            f"delta_eta ({self.delta_eta}) + delta_LTT ({self.delta_LTT}) "
            f"must equal delta_total ({self.delta_total})"
        )
    return self
```

- [ ] **Step 4: Re-run tests and full suite**

```
pytest cascade_rc/tests/test_budget_split.py -v
pytest cascade_rc/tests/ -v --tb=short -q
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/config.py cascade_rc/tests/test_budget_split.py
git commit -m "fix(config): use math.isclose in LTTBudget validator for float-precision safety"
```

---

## Task 2: Add `order_fn` parameter to `calibrate()`

**Files:**
- Modify: `cascade_rc/calibration/main_calibrate.py`
- Create: `cascade_rc/tests/test_walk_ordering.py`

- [ ] **Step 1: Create test file with order_fn test**

Create `cascade_rc/tests/test_walk_ordering.py`:

```python
from __future__ import annotations

import sys
import types
import unittest.mock as mock
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
    df = generate_paper_running_example(n=n, seed=seed)
    df = df.rename(columns={"y": "y_abstract"})
    if n_calib_pos is not None:
        pos_iloc = np.where(df["y_abstract"].to_numpy() == 1)[0]
        neg_iloc = np.where(df["y_abstract"].to_numpy() == 0)[0]
        is_calib = np.zeros(len(df), dtype=int)
        is_calib[pos_iloc[:n_calib_pos]] = 1
        is_calib[neg_iloc[:200]] = 1
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


def test_calibrate_accepts_order_fn(tmp_path: Path) -> None:
    """calibrate() must accept order_fn kwarg and complete without error."""
    from cascade_rc.calibration.main_calibrate import calibrate
    from cascade_rc.calibration.walker import safest_to_riskiest_order
    from cascade_rc.certificates.store import CertificationResult
    from cascade_rc.config import CascadeRCConfig, LTTBudget

    calib_parquet = _make_synthetic_parquet(tmp_path, n=10_000, seed=0)
    config = CascadeRCConfig(
        ltt=LTTBudget(alpha=0.10, delta_total=0.10, delta_eta=0.03, delta_LTT=0.07, K=5),
        artefact_dir=tmp_path,
    )

    def reversed_order(grid: np.ndarray) -> np.ndarray:
        return safest_to_riskiest_order(grid)[::-1]

    result = calibrate(
        "topic_rev", calib_parquet, config, order_fn=reversed_order
    )
    # Must complete (certify or abstain) without raising TypeError
    assert isinstance(result, (CertificationResult, tuple))
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest cascade_rc/tests/test_walk_ordering.py::test_calibrate_accepts_order_fn -v
```

Expected: FAIL — `TypeError: calibrate() got an unexpected keyword argument 'order_fn'`

- [ ] **Step 3: Modify `calibrate()` in `cascade_rc/calibration/main_calibrate.py`**

Add `Callable` to the imports block at the top of the file. The existing `from __future__ import annotations` means the imports section reads:

```python
from typing import Callable   # add this line alongside existing typing imports
```

Change the `calibrate` signature (add `order_fn` as last parameter):

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

Replace the one line `order = safest_to_riskiest_order(theta_g)` (currently line 199) with:

```python
    order = (order_fn if order_fn is not None else safest_to_riskiest_order)(theta_g)
```

- [ ] **Step 4: Run test**

```
pytest cascade_rc/tests/test_walk_ordering.py::test_calibrate_accepts_order_fn -v
```

Expected: PASS

- [ ] **Step 5: Confirm no regressions**

```
pytest cascade_rc/tests/ -v --tb=short -q
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add cascade_rc/calibration/main_calibrate.py cascade_rc/tests/test_walk_ordering.py
git commit -m "feat(calibrate): add optional order_fn parameter for walk-ordering ablations"
```

---

## Task 3: `budget_split.py` — schema, constants, dry-run

**Files:**
- Create: `cascade_rc/ablations/budget_split.py`
- Modify: `cascade_rc/tests/test_budget_split.py`

- [ ] **Step 1: Add dry-run schema test**

Append to `cascade_rc/tests/test_budget_split.py` (add these imports at the top of the file after the existing ones):

```python
import json
from pathlib import Path

import numpy as np
import pandas as pd

from cascade_rc.synthetic.beta_mixture import generate_paper_running_example


def _make_synthetic_parquet(
    tmp_path: Path,
    n: int = 1_000,
    seed: int = 0,
    n_calib_pos: int | None = None,
    filename: str = "TOPIC_A.parquet",
) -> Path:
    df = generate_paper_running_example(n=n, seed=seed)
    df = df.rename(columns={"y": "y_abstract"})
    if n_calib_pos is not None:
        pos_iloc = np.where(df["y_abstract"].to_numpy() == 1)[0]
        neg_iloc = np.where(df["y_abstract"].to_numpy() == 0)[0]
        is_calib = np.zeros(len(df), dtype=int)
        is_calib[pos_iloc[:n_calib_pos]] = 1
        is_calib[neg_iloc[:200]] = 1
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
```

Then add the test function:

```python
def test_dry_run_schema(tmp_path: Path) -> None:
    """--dry-run produces a zero-row parquet with the exact 14-column schema."""
    from cascade_rc.ablations.budget_split import PARQUET_SCHEMA, run_sweep

    run_sweep(data_dir=tmp_path, out_dir=tmp_path / "out", dry_run=True)

    parquet_path = tmp_path / "out" / "budget_split.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert len(df) == 0, f"Expected 0 rows, got {len(df)}"
    assert list(df.columns) == list(PARQUET_SCHEMA.keys()), (
        f"Column mismatch:\n  got:  {list(df.columns)}\n  want: {list(PARQUET_SCHEMA.keys())}"
    )
    for col, expected_dtype in PARQUET_SCHEMA.items():
        assert str(df[col].dtype) == str(expected_dtype), (
            f"Column '{col}': expected '{expected_dtype}', got '{df[col].dtype}'"
        )
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest cascade_rc/tests/test_budget_split.py::test_dry_run_schema -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cascade_rc.ablations.budget_split'`

- [ ] **Step 3: Create `cascade_rc/ablations/budget_split.py`**

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

HEADLINE_DTA_TOPICS: list[str] = ["CD008874", "CD012080", "CD012768"]

BUDGET_SPLITS: list[tuple[float, float]] = [
    (0.01, 0.09),
    (0.03, 0.07),
    (0.05, 0.05),
    (0.07, 0.03),
    (0.09, 0.01),
]

PARQUET_SCHEMA: dict[str, str] = {
    "delta_eta": "float64",
    "delta_ltt": "float64",
    "topic_id": "object",
    "m_plus": "int64",
    "abstention": "bool",
    "wss_95": "float64",
    "wss_status": "object",
    "achieved_recall": "float64",
    "n_certified": "int64",
    "mean_eta_lcb": "float64",
    "theta_hat_lambda_lo": "float64",
    "theta_hat_lambda_hi": "float64",
    "theta_hat_tau_se": "float64",
    "alpha_dagger_at_theta": "float64",
}


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {col: pd.Series(dtype=dtype) for col, dtype in PARQUET_SCHEMA.items()}
    )


def _plot_pareto(df: pd.DataFrame, out_dir: Path) -> None:
    pass


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
) -> pd.DataFrame:
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "budget_split.parquet", index=False)
        return df_empty

    raise NotImplementedError("_run_topic not yet implemented")
```

- [ ] **Step 4: Run dry-run schema test**

```
pytest cascade_rc/tests/test_budget_split.py::test_dry_run_schema -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/ablations/budget_split.py cascade_rc/tests/test_budget_split.py
git commit -m "feat(budget_split): add parquet schema, constants, and dry-run skeleton"
```

---

## Task 4: `budget_split.py` — `_run_topic` and `run_sweep`

**Files:**
- Modify: `cascade_rc/ablations/budget_split.py`
- Modify: `cascade_rc/tests/test_budget_split.py`

- [ ] **Step 1: Add abstention-row schema test**

Append to `cascade_rc/tests/test_budget_split.py`:

```python
import sys
import types
import unittest.mock as mock


def test_run_sweep_abstention_row_schema(tmp_path: Path) -> None:
    """When calibrate() abstains for every call, run_sweep writes correct abstention rows."""
    from cascade_rc.ablations.budget_split import run_sweep

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_synthetic_parquet(data_dir, n_calib_pos=50, filename="CD008874.parquet")

    _stub_modules: list[str] = []
    for mod_name in ("confseq", "confseq.betting"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            stub.betting_lower_cs = mock.MagicMock()
            stub.lambda_predmix_eb = mock.MagicMock()
            sys.modules[mod_name] = stub
            _stub_modules.append(mod_name)

    try:
        with mock.patch(
            "cascade_rc.calibration.main_calibrate.calibrate",
            return_value=(None, None, "abstained:m_plus=10<26"),
        ), mock.patch("cascade_rc.ablations.budget_split._plot_pareto"):
            df = run_sweep(
                data_dir=data_dir,
                out_dir=tmp_path / "out",
                topics_filter=["CD008874"],
            )
    finally:
        for mod_name in _stub_modules:
            sys.modules.pop(mod_name, None)
        for key in list(sys.modules):
            if any(s in key for s in ("main_calibrate", "wsr_lcb", "surrogate_loss")):
                sys.modules.pop(key, None)

    # 5 splits × 1 topic = 5 rows
    assert len(df) == 5, f"Expected 5 rows, got {len(df)}"
    assert df["abstention"].all()
    assert (df["wss_status"] == "abstained").all()
    assert df["wss_95"].isna().all()
    assert df["achieved_recall"].isna().all()
    assert (df["n_certified"] == 0).all()
    assert df["theta_hat_lambda_lo"].isna().all()
    assert df["alpha_dagger_at_theta"].isna().all()
    assert set(df["delta_eta"].unique()) == {0.01, 0.03, 0.05, 0.07, 0.09}
    assert set(df["delta_ltt"].unique()) == {0.09, 0.07, 0.05, 0.03, 0.01}
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest cascade_rc/tests/test_budget_split.py::test_run_sweep_abstention_row_schema -v
```

Expected: FAIL — `NotImplementedError: _run_topic not yet implemented`

- [ ] **Step 3: Implement helpers and `_run_topic` in `budget_split.py`**

Add these imports at the top of `cascade_rc/ablations/budget_split.py`:

```python
import numpy as np
from joblib import Parallel, delayed

from cascade_rc.config import CascadeRCConfig, LTTBudget
from cascade_rc.evaluation.metrics import wss_at_recall
```

Add these functions before `_plot_pareto`:

```python
def _compute_wss(result: object, df_full: pd.DataFrame) -> dict:
    df_test = df_full[df_full["is_calib"] == 0]
    s = df_test["s"].to_numpy(dtype=np.float64)
    y = df_test["y_abstract"].to_numpy(dtype=np.int64)
    lam_lo = float(result.theta_hat[0])  # type: ignore[union-attr]
    auto_reject = s < lam_lo
    predictions = (~auto_reject).astype(int)
    return wss_at_recall(predictions, y, target_recall=0.95)


def _find_theta_hat_idx(result: object) -> int:
    """Return index of theta_hat in theta_grid (exact float match guaranteed)."""
    matches = np.where(
        np.all(result.theta_grid == result.theta_hat[np.newaxis, :], axis=1)  # type: ignore[union-attr]
    )[0]
    return int(matches[0])


def _run_topic(
    topic_id: str,
    parquet_path: Path,
    delta_eta: float,
    delta_ltt: float,
    config: CascadeRCConfig,
    out_dir: Path,
) -> dict:
    from cascade_rc.calibration.main_calibrate import calibrate

    patched_ltt = LTTBudget(
        alpha=config.ltt.alpha,
        delta_total=config.ltt.delta_total,
        delta_eta=delta_eta,
        delta_LTT=delta_ltt,
        K=config.ltt.K,
        B=config.ltt.B,
        ensemble_temperature=config.ltt.ensemble_temperature,
        c_human=config.ltt.c_human,
        c_llm=config.ltt.c_llm,
        delta_bootstrap=config.ltt.delta_bootstrap,
    )
    patched_config = config.model_copy(update={"ltt": patched_ltt})

    artefact_dir = (
        out_dir / "calibration_cache"
        / f"{topic_id}_de{delta_eta:.2f}_dl{delta_ltt:.2f}"
    )
    artefact_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(parquet_path)
    m_plus = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())

    result = calibrate(topic_id, parquet_path, patched_config, artefact_dir=artefact_dir)

    if isinstance(result, tuple):
        return {
            "delta_eta": delta_eta,
            "delta_ltt": delta_ltt,
            "topic_id": topic_id,
            "m_plus": m_plus,
            "abstention": True,
            "wss_95": float("nan"),
            "wss_status": "abstained",
            "achieved_recall": float("nan"),
            "n_certified": 0,
            "mean_eta_lcb": float("nan"),
            "theta_hat_lambda_lo": float("nan"),
            "theta_hat_lambda_hi": float("nan"),
            "theta_hat_tau_se": float("nan"),
            "alpha_dagger_at_theta": float("nan"),
        }

    wss_dict = _compute_wss(result, df)
    theta_idx = _find_theta_hat_idx(result)

    return {
        "delta_eta": delta_eta,
        "delta_ltt": delta_ltt,
        "topic_id": topic_id,
        "m_plus": result.m_plus,
        "abstention": False,
        "wss_95": wss_dict["wss"],
        "wss_status": wss_dict["status"],
        "achieved_recall": wss_dict["achieved_recall"],
        "n_certified": int(result.lambda_hat_mask.sum()),
        "mean_eta_lcb": float(np.mean(result.eta_lcb_grid)),
        "theta_hat_lambda_lo": float(result.theta_hat[0]),
        "theta_hat_lambda_hi": float(result.theta_hat[1]),
        "theta_hat_tau_se": float(result.theta_hat[2]),
        "alpha_dagger_at_theta": float(result.alpha_dagger_grid[theta_idx]),
    }
```

- [ ] **Step 4: Replace the `run_sweep` stub with the real implementation**

```python
def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
) -> pd.DataFrame:
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "budget_split.parquet", index=False)
        return df_empty

    topics = topics_filter if topics_filter is not None else HEADLINE_DTA_TOPICS
    parquet_paths = {p.stem: p for p in sorted(data_dir.glob("*.parquet"))}
    available = [t for t in topics if t in parquet_paths]

    config = CascadeRCConfig()

    tasks = [
        (topic_id, parquet_paths[topic_id], delta_eta, delta_ltt, config, out_dir)
        for topic_id in available
        for delta_eta, delta_ltt in BUDGET_SPLITS
    ]

    results: list[dict] = Parallel(n_jobs=n_jobs, backend="loky")(
        delayed(_run_topic)(*args) for args in tasks
    )

    df = pd.DataFrame(results).astype(PARQUET_SCHEMA) if results else _empty_dataframe()
    df.to_parquet(out_dir / "budget_split.parquet", index=False)

    if not df.empty:
        _plot_pareto(df, out_dir)

    return df
```

- [ ] **Step 5: Run abstention test**

```
pytest cascade_rc/tests/test_budget_split.py::test_run_sweep_abstention_row_schema -v
```

Expected: PASS

- [ ] **Step 6: Run all budget_split tests**

```
pytest cascade_rc/tests/test_budget_split.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add cascade_rc/ablations/budget_split.py cascade_rc/tests/test_budget_split.py
git commit -m "feat(budget_split): implement _run_topic and run_sweep"
```

---

## Task 5: `budget_split.py` — Pareto plot and CLI

**Files:**
- Modify: `cascade_rc/ablations/budget_split.py`

- [ ] **Step 1: Implement `_plot_pareto`**

Replace the `pass` stub for `_plot_pareto`:

```python
def _plot_pareto(df: pd.DataFrame, out_dir: Path) -> None:
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.cm as cm

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    delta_etas = sorted(df["delta_eta"].unique())
    topics = sorted(df["topic_id"].unique())
    markers = ["o", "s", "^"]
    cmap = cm.get_cmap("plasma", len(delta_etas))

    fig, ax = plt.subplots(figsize=(8, 6))

    for t_idx, topic_id in enumerate(topics):
        df_t = df[df["topic_id"] == topic_id]
        marker = markers[t_idx % len(markers)]
        for de_idx, de in enumerate(delta_etas):
            rows = df_t[df_t["delta_eta"] == de]
            if rows.empty:
                continue
            r = rows.iloc[0]
            color = cmap(de_idx)
            if r["wss_status"] == "ok":
                ax.scatter(
                    r["n_certified"], r["wss_95"],
                    color=color, marker=marker, s=80,
                    label=f"δ_η={de:.2f}" if t_idx == 0 else "",
                )
            else:
                ax.scatter(
                    r["n_certified"], 0.0,
                    color="red", marker="x", s=120, linewidths=2,
                )

    ax.set_xlabel("|Λ̂| (certified set size)")
    ax.set_ylabel("WSS@95")
    ax.set_title("Budget Split: |Λ̂| vs WSS@95 by δ_η (Pareto Front)")
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(dict(zip(labels, handles)).values(),
                  dict(zip(labels, handles)).keys(),
                  fontsize=8, loc="lower right")

    # Inset: abstention heatmap (splits × topics)
    ax_ins = ax.inset_axes([0.65, 0.62, 0.33, 0.32])
    abstention_mat = np.zeros((len(delta_etas), len(topics)), dtype=float)
    for i, de in enumerate(delta_etas):
        for j, topic_id in enumerate(topics):
            rows = df[(df["delta_eta"] == de) & (df["topic_id"] == topic_id)]
            if not rows.empty:
                abstention_mat[i, j] = float(rows.iloc[0]["abstention"])
    ax_ins.imshow(abstention_mat, aspect="auto", cmap="Reds", vmin=0, vmax=1)
    ax_ins.set_xticks(range(len(topics)))
    ax_ins.set_xticklabels([t[-6:] for t in topics], fontsize=5, rotation=45)
    ax_ins.set_yticks(range(len(delta_etas)))
    ax_ins.set_yticklabels([f"{de:.2f}" for de in delta_etas], fontsize=5)
    ax_ins.set_title("abstention", fontsize=6)

    plt.tight_layout()
    fig.savefig(plot_dir / "budget_split_pareto.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
```

- [ ] **Step 2: Add `main()` at the bottom of `budget_split.py`**

```python
def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Budget-split ablation sweep for CASCADE-RC",
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
        help="Output directory for parquet and plots",
    )
    parser.add_argument(
        "--topics", nargs="+", default=None,
        help="Topic IDs to include (default: 3 headline DTA topics)",
    )
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    df = run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        topics_filter=args.topics,
        n_jobs=args.n_jobs,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(f"DRY-RUN: schema written to {args.out_dir / 'budget_split.parquet'}")
    else:
        print(f"Sweep complete: {len(df)} rows, {df['topic_id'].nunique()} topics")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify CLI dry-run**

```bash
python3 -m cascade_rc.ablations.budget_split --dry-run --out-dir /tmp/bs_test
```

Expected: `DRY-RUN: schema written to /tmp/bs_test/budget_split.parquet`

- [ ] **Step 4: Run all tests**

```
pytest cascade_rc/tests/test_budget_split.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/ablations/budget_split.py
git commit -m "feat(budget_split): add pareto plot and argparse CLI"
```

---

## Task 6: `walk_ordering.py` — ordering functions, schema, dry-run

**Files:**
- Create: `cascade_rc/ablations/walk_ordering.py`
- Modify: `cascade_rc/tests/test_walk_ordering.py`

- [ ] **Step 1: Add ordering-function and dry-run tests**

Append to `cascade_rc/tests/test_walk_ordering.py`:

```python
def test_riskiest_to_safest_is_reverse_of_default() -> None:
    """_order_riskiest_to_safest must be the exact reversal of safest_to_riskiest_order."""
    from cascade_rc.ablations.walk_ordering import DETERMINISTIC_ORDERS
    from cascade_rc.calibration.surrogate_loss import grid as sg

    g = sg(K=5)
    safe_order = DETERMINISTIC_ORDERS["safest_to_riskiest"](g)
    risky_order = DETERMINISTIC_ORDERS["riskiest_to_safest"](g)
    np.testing.assert_array_equal(safe_order, risky_order[::-1])


def test_lex_tau_se_first_sorts_by_tau_ascending() -> None:
    """lex_tau_se_first must sort by τ_SE as primary ascending key."""
    from cascade_rc.ablations.walk_ordering import DETERMINISTIC_ORDERS

    g = np.array([
        [0.1, 0.5, 0.9],
        [0.1, 0.5, 0.1],
        [0.0, 0.5, 0.5],
        [0.0, 0.5, 0.3],
    ])
    order = DETERMINISTIC_ORDERS["lex_tau_se_first"](g)
    tau_sorted = g[order, 2]
    assert list(tau_sorted) == sorted(tau_sorted.tolist()), (
        f"τ_SE must be non-decreasing after lex_tau_se_first: {tau_sorted}"
    )


def test_make_random_order_fn_is_reproducible_permutation() -> None:
    """_make_random_order_fn(seed) must return a stable full permutation."""
    from cascade_rc.ablations.walk_ordering import _make_random_order_fn
    from cascade_rc.calibration.surrogate_loss import grid as sg

    g = sg(K=5)
    G = len(g)
    fn_42 = _make_random_order_fn(42)
    order_a = fn_42(g)
    order_b = fn_42(g)

    assert len(order_a) == G
    assert set(order_a.tolist()) == set(range(G)), "must cover all G indices"
    np.testing.assert_array_equal(order_a, order_b, "same seed → identical order")

    fn_43 = _make_random_order_fn(43)
    assert not np.array_equal(fn_43(g), order_a), "different seeds must differ"


def test_dry_run_schema_walk_ordering(tmp_path: Path) -> None:
    """--dry-run produces a zero-row parquet with the exact 14-column schema."""
    from cascade_rc.ablations.walk_ordering import PARQUET_SCHEMA, run_sweep

    run_sweep(data_dir=tmp_path, out_dir=tmp_path / "out", dry_run=True)

    parquet_path = tmp_path / "out" / "walk_ordering.parquet"
    assert parquet_path.exists()

    df = pd.read_parquet(parquet_path)
    assert len(df) == 0
    assert list(df.columns) == list(PARQUET_SCHEMA.keys()), (
        f"Column mismatch:\n  got:  {list(df.columns)}\n  want: {list(PARQUET_SCHEMA.keys())}"
    )
    for col, expected_dtype in PARQUET_SCHEMA.items():
        assert str(df[col].dtype) == str(expected_dtype), (
            f"Column '{col}': expected '{expected_dtype}', got '{df[col].dtype}'"
        )
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest cascade_rc/tests/test_walk_ordering.py::test_riskiest_to_safest_is_reverse_of_default \
       cascade_rc/tests/test_walk_ordering.py::test_lex_tau_se_first_sorts_by_tau_ascending \
       cascade_rc/tests/test_walk_ordering.py::test_make_random_order_fn_is_reproducible_permutation \
       cascade_rc/tests/test_walk_ordering.py::test_dry_run_schema_walk_ordering -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'cascade_rc.ablations.walk_ordering'`

- [ ] **Step 3: Create `cascade_rc/ablations/walk_ordering.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from cascade_rc.calibration.walker import safest_to_riskiest_order

HEADLINE_DTA_TOPICS: list[str] = ["CD008874", "CD012080", "CD012768"]
RANDOM_SEEDS: list[int] = [42, 43, 44, 45, 46]


def _order_riskiest_to_safest(grid: np.ndarray) -> np.ndarray:
    return safest_to_riskiest_order(grid)[::-1]


def _order_lex_tau_se_first(grid: np.ndarray) -> np.ndarray:
    return np.lexsort((grid[:, 0], grid[:, 1], grid[:, 2]))


DETERMINISTIC_ORDERS: dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "safest_to_riskiest": safest_to_riskiest_order,
    "riskiest_to_safest": _order_riskiest_to_safest,
    "lex_tau_se_first": _order_lex_tau_se_first,
}


def _make_random_order_fn(seed: int) -> Callable[[np.ndarray], np.ndarray]:
    def _order(grid: np.ndarray) -> np.ndarray:
        return np.random.default_rng(seed).permutation(len(grid))
    return _order


PARQUET_SCHEMA: dict[str, str] = {
    "order_name": "object",
    "order_seed": "int64",
    "topic_id": "object",
    "m_plus": "int64",
    "abstention": "bool",
    "wss_95": "float64",
    "wss_status": "object",
    "achieved_recall": "float64",
    "n_certified": "int64",
    "mean_eta_lcb": "float64",
    "theta_hat_lambda_lo": "float64",
    "theta_hat_lambda_hi": "float64",
    "theta_hat_tau_se": "float64",
    "alpha_dagger_at_theta": "float64",
}


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {col: pd.Series(dtype=dtype) for col, dtype in PARQUET_SCHEMA.items()}
    )


def _plot_n_certified(df: pd.DataFrame, out_dir: Path) -> None:
    pass


def _plot_wss_95(df: pd.DataFrame, out_dir: Path) -> None:
    pass


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
) -> pd.DataFrame:
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "walk_ordering.parquet", index=False)
        return df_empty

    raise NotImplementedError("_run_topic not yet implemented")
```

- [ ] **Step 4: Run the four tests**

```
pytest cascade_rc/tests/test_walk_ordering.py::test_riskiest_to_safest_is_reverse_of_default \
       cascade_rc/tests/test_walk_ordering.py::test_lex_tau_se_first_sorts_by_tau_ascending \
       cascade_rc/tests/test_walk_ordering.py::test_make_random_order_fn_is_reproducible_permutation \
       cascade_rc/tests/test_walk_ordering.py::test_dry_run_schema_walk_ordering -v
```

Expected: all 4 PASS

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/ablations/walk_ordering.py cascade_rc/tests/test_walk_ordering.py
git commit -m "feat(walk_ordering): add ordering functions, schema, and dry-run skeleton"
```

---

## Task 7: `walk_ordering.py` — `_run_topic` and `run_sweep`

**Files:**
- Modify: `cascade_rc/ablations/walk_ordering.py`
- Modify: `cascade_rc/tests/test_walk_ordering.py`

- [ ] **Step 1: Add abstention-row schema test**

Append to `cascade_rc/tests/test_walk_ordering.py`:

```python
def test_run_sweep_abstention_row_schema(tmp_path: Path) -> None:
    """run_sweep produces (3 det + 5 random) × 1 topic = 8 abstention rows with correct schema."""
    from cascade_rc.ablations.walk_ordering import run_sweep

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _make_synthetic_parquet(data_dir, n_calib_pos=50, filename="CD008874.parquet")

    _stub_modules: list[str] = []
    for mod_name in ("confseq", "confseq.betting"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            stub.betting_lower_cs = mock.MagicMock()
            stub.lambda_predmix_eb = mock.MagicMock()
            sys.modules[mod_name] = stub
            _stub_modules.append(mod_name)

    try:
        with mock.patch(
            "cascade_rc.calibration.main_calibrate.calibrate",
            return_value=(None, None, "abstained:m_plus=10<26"),
        ), mock.patch("cascade_rc.ablations.walk_ordering._plot_n_certified"), \
           mock.patch("cascade_rc.ablations.walk_ordering._plot_wss_95"):
            df = run_sweep(
                data_dir=data_dir,
                out_dir=tmp_path / "out",
                topics_filter=["CD008874"],
            )
    finally:
        for mod_name in _stub_modules:
            sys.modules.pop(mod_name, None)
        for key in list(sys.modules):
            if any(s in key for s in ("main_calibrate", "wsr_lcb", "surrogate_loss")):
                sys.modules.pop(key, None)

    assert len(df) == 8, f"Expected 8 rows (3 det + 5 random) × 1 topic, got {len(df)}"
    assert df["abstention"].all()
    assert (df["wss_status"] == "abstained").all()
    assert (df["n_certified"] == 0).all()

    counts = df["order_name"].value_counts()
    assert counts["random"] == 5
    assert counts["safest_to_riskiest"] == 1
    assert counts["riskiest_to_safest"] == 1
    assert counts["lex_tau_se_first"] == 1

    det_rows = df[df["order_name"] != "random"]
    assert (det_rows["order_seed"] == -1).all(), "deterministic rows must use seed sentinel -1"

    rand_rows = df[df["order_name"] == "random"]
    assert set(rand_rows["order_seed"].tolist()) == {42, 43, 44, 45, 46}
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest cascade_rc/tests/test_walk_ordering.py::test_run_sweep_abstention_row_schema -v
```

Expected: FAIL — `NotImplementedError: _run_topic not yet implemented`

- [ ] **Step 3: Add imports and implement helpers in `walk_ordering.py`**

Add these imports at the top of `cascade_rc/ablations/walk_ordering.py`:

```python
from joblib import Parallel, delayed

from cascade_rc.config import CascadeRCConfig
from cascade_rc.evaluation.metrics import wss_at_recall
```

Add these functions before `_plot_n_certified`:

```python
def _compute_wss(result: object, df_full: pd.DataFrame) -> dict:
    df_test = df_full[df_full["is_calib"] == 0]
    s = df_test["s"].to_numpy(dtype=np.float64)
    y = df_test["y_abstract"].to_numpy(dtype=np.int64)
    lam_lo = float(result.theta_hat[0])  # type: ignore[union-attr]
    auto_reject = s < lam_lo
    predictions = (~auto_reject).astype(int)
    return wss_at_recall(predictions, y, target_recall=0.95)


def _find_theta_hat_idx(result: object) -> int:
    matches = np.where(
        np.all(result.theta_grid == result.theta_hat[np.newaxis, :], axis=1)  # type: ignore[union-attr]
    )[0]
    return int(matches[0])


def _run_topic(
    topic_id: str,
    parquet_path: Path,
    order_name: str,
    order_seed: int,
    config: CascadeRCConfig,
    out_dir: Path,
) -> dict:
    from cascade_rc.calibration.main_calibrate import calibrate

    if order_name == "random":
        order_fn = _make_random_order_fn(order_seed)
    else:
        order_fn = DETERMINISTIC_ORDERS[order_name]

    artefact_dir = (
        out_dir / "calibration_cache"
        / f"{topic_id}_{order_name}_{order_seed}"
    )
    artefact_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(parquet_path)
    m_plus = int(((df["is_calib"] == 1) & (df["y_abstract"] == 1)).sum())

    result = calibrate(
        topic_id, parquet_path, config,
        artefact_dir=artefact_dir,
        order_fn=order_fn,
    )

    if isinstance(result, tuple):
        return {
            "order_name": order_name,
            "order_seed": order_seed,
            "topic_id": topic_id,
            "m_plus": m_plus,
            "abstention": True,
            "wss_95": float("nan"),
            "wss_status": "abstained",
            "achieved_recall": float("nan"),
            "n_certified": 0,
            "mean_eta_lcb": float("nan"),
            "theta_hat_lambda_lo": float("nan"),
            "theta_hat_lambda_hi": float("nan"),
            "theta_hat_tau_se": float("nan"),
            "alpha_dagger_at_theta": float("nan"),
        }

    wss_dict = _compute_wss(result, df)
    theta_idx = _find_theta_hat_idx(result)

    return {
        "order_name": order_name,
        "order_seed": order_seed,
        "topic_id": topic_id,
        "m_plus": result.m_plus,
        "abstention": False,
        "wss_95": wss_dict["wss"],
        "wss_status": wss_dict["status"],
        "achieved_recall": wss_dict["achieved_recall"],
        "n_certified": int(result.lambda_hat_mask.sum()),
        "mean_eta_lcb": float(np.mean(result.eta_lcb_grid)),
        "theta_hat_lambda_lo": float(result.theta_hat[0]),
        "theta_hat_lambda_hi": float(result.theta_hat[1]),
        "theta_hat_tau_se": float(result.theta_hat[2]),
        "alpha_dagger_at_theta": float(result.alpha_dagger_grid[theta_idx]),
    }
```

- [ ] **Step 4: Replace the `run_sweep` stub with the real implementation**

```python
def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics_filter: list[str] | None = None,
    n_jobs: int = 1,
    dry_run: bool = False,
) -> pd.DataFrame:
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df_empty = _empty_dataframe()
        df_empty.to_parquet(out_dir / "walk_ordering.parquet", index=False)
        return df_empty

    topics = topics_filter if topics_filter is not None else HEADLINE_DTA_TOPICS
    parquet_paths = {p.stem: p for p in sorted(data_dir.glob("*.parquet"))}
    available = [t for t in topics if t in parquet_paths]

    config = CascadeRCConfig()

    tasks: list[tuple] = []
    for topic_id in available:
        for order_name in DETERMINISTIC_ORDERS:
            tasks.append(
                (topic_id, parquet_paths[topic_id], order_name, -1, config, out_dir)
            )
        for seed in RANDOM_SEEDS:
            tasks.append(
                (topic_id, parquet_paths[topic_id], "random", seed, config, out_dir)
            )

    results: list[dict] = Parallel(n_jobs=n_jobs, backend="loky")(
        delayed(_run_topic)(*args) for args in tasks
    )

    df = pd.DataFrame(results).astype(PARQUET_SCHEMA) if results else _empty_dataframe()
    df.to_parquet(out_dir / "walk_ordering.parquet", index=False)

    if not df.empty:
        _plot_n_certified(df, out_dir)
        _plot_wss_95(df, out_dir)

    return df
```

- [ ] **Step 5: Run the abstention test**

```
pytest cascade_rc/tests/test_walk_ordering.py::test_run_sweep_abstention_row_schema -v
```

Expected: PASS

- [ ] **Step 6: Run all walk_ordering tests**

```
pytest cascade_rc/tests/test_walk_ordering.py -v
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add cascade_rc/ablations/walk_ordering.py cascade_rc/tests/test_walk_ordering.py
git commit -m "feat(walk_ordering): implement _run_topic and run_sweep"
```

---

## Task 8: `walk_ordering.py` — plots and CLI

**Files:**
- Modify: `cascade_rc/ablations/walk_ordering.py`

- [ ] **Step 1: Implement `_plot_n_certified`**

Replace the `pass` stub:

```python
def _plot_n_certified(df: pd.DataFrame, out_dir: Path) -> None:
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    topics = sorted(df["topic_id"].unique())
    det_names = list(DETERMINISTIC_ORDERS.keys())
    n_bars = len(det_names) + 1
    x = np.arange(len(topics))
    width = 0.18
    offsets = np.linspace(-(n_bars - 1) * width / 2, (n_bars - 1) * width / 2, n_bars)

    fig, ax = plt.subplots(figsize=(9, 5))

    for b_idx, order_name in enumerate(det_names):
        vals = [
            int(df[(df["topic_id"] == t) & (df["order_name"] == order_name)]["n_certified"].iloc[0])
            if not df[(df["topic_id"] == t) & (df["order_name"] == order_name)].empty
            else 0
            for t in topics
        ]
        ax.bar(x + offsets[b_idx], vals, width, label=order_name)

    rand_means = []
    rand_stds = []
    for t in topics:
        vals = df[(df["topic_id"] == t) & (df["order_name"] == "random")]["n_certified"].to_numpy(dtype=float)
        rand_means.append(float(vals.mean()) if len(vals) > 0 else 0.0)
        rand_stds.append(float(vals.std()) if len(vals) > 0 else 0.0)
    ax.bar(x + offsets[-1], rand_means, width, yerr=rand_stds, capsize=4, label="random (mean±std)")

    ax.set_xlabel("Topic")
    ax.set_ylabel("|Λ̂| (certified set size)")
    ax.set_title("Walk Ordering: Certified Set Size per Topic")
    ax.set_xticks(x)
    ax.set_xticklabels([t[-6:] for t in topics])
    ax.legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(plot_dir / "walk_ordering_n_certified.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
```

- [ ] **Step 2: Implement `_plot_wss_95`**

Replace the `pass` stub:

```python
def _plot_wss_95(df: pd.DataFrame, out_dir: Path) -> None:
    import matplotlib
    if matplotlib.get_backend().lower() != "agg":
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    topics = sorted(df["topic_id"].unique())
    det_names = list(DETERMINISTIC_ORDERS.keys())
    n_bars = len(det_names) + 1
    x = np.arange(len(topics))
    width = 0.18
    offsets = np.linspace(-(n_bars - 1) * width / 2, (n_bars - 1) * width / 2, n_bars)

    fig, ax = plt.subplots(figsize=(9, 5))

    for b_idx, order_name in enumerate(det_names):
        vals = []
        for t in topics:
            rows = df[(df["topic_id"] == t) & (df["order_name"] == order_name)]
            if rows.empty or rows.iloc[0]["wss_status"] != "ok":
                vals.append(0.0)
                if not rows.empty:
                    ax.text(
                        x[topics.index(t)] + offsets[b_idx], 0.02,
                        "✗", color="red", ha="center", fontsize=10,
                    )
            else:
                vals.append(float(rows.iloc[0]["wss_95"]))
        ax.bar(x + offsets[b_idx], vals, width, label=order_name)

    rand_means = []
    rand_stds = []
    for t in topics:
        ok_rows = df[
            (df["topic_id"] == t) & (df["order_name"] == "random") & (df["wss_status"] == "ok")
        ]
        vals = ok_rows["wss_95"].to_numpy(dtype=float)
        rand_means.append(float(vals.mean()) if len(vals) > 0 else 0.0)
        rand_stds.append(float(vals.std()) if len(vals) > 0 else 0.0)
    ax.bar(x + offsets[-1], rand_means, width, yerr=rand_stds, capsize=4, label="random (mean±std)")

    ax.set_xlabel("Topic")
    ax.set_ylabel("WSS@95")
    ax.set_title("Walk Ordering: WSS@95 per Topic")
    ax.set_xticks(x)
    ax.set_xticklabels([t[-6:] for t in topics])
    ax.legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(plot_dir / "walk_ordering_wss_95.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
```

- [ ] **Step 3: Add `main()`**

```python
def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Walk-ordering ablation sweep for CASCADE-RC",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir", type=Path,
        default=Path("artefacts/cascade_rc/data"),
    )
    parser.add_argument(
        "--out-dir", type=Path,
        default=Path("artefacts/cascade_rc/ablations"),
    )
    parser.add_argument("--topics", nargs="+", default=None)
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    df = run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        topics_filter=args.topics,
        n_jobs=args.n_jobs,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(f"DRY-RUN: schema written to {args.out_dir / 'walk_ordering.parquet'}")
    else:
        print(f"Sweep complete: {len(df)} rows, {df['topic_id'].nunique()} topics")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify CLI dry-run**

```bash
python3 -m cascade_rc.ablations.walk_ordering --dry-run --out-dir /tmp/wo_test
```

Expected: `DRY-RUN: schema written to /tmp/wo_test/walk_ordering.parquet`

- [ ] **Step 5: Run full test suite**

```
pytest cascade_rc/tests/ -v --tb=short -q
```

Expected: all PASS — no regressions.

- [ ] **Step 6: Commit**

```bash
git add cascade_rc/ablations/walk_ordering.py
git commit -m "feat(walk_ordering): add grouped-bar plots and argparse CLI"
```

---

## Acceptance Criteria Verification

After running on real data (`artefacts/cascade_rc/data/`), verify:

```python
import pandas as pd

bs = pd.read_parquet("artefacts/cascade_rc/ablations/budget_split.parquet")
wo = pd.read_parquet("artefacts/cascade_rc/ablations/walk_ordering.parquet")

# AC1: budget_split parquet
assert len(bs) == 15, f"Expected 15 rows, got {len(bs)}"
assert len(bs.columns) == 14

# AC2: walk_ordering parquet
assert len(wo) == 24, f"Expected 24 rows, got {len(wo)}"
assert len(wo.columns) == 14

# AC3: safest_to_riskiest dominates random mean WSS@95 on ≥2/3 DTA topics
topics = ["CD008874", "CD012080", "CD012768"]
wins = 0
for t in topics:
    safe_wss = wo[(wo["topic_id"] == t) & (wo["order_name"] == "safest_to_riskiest")]["wss_95"].iloc[0]
    rand_mean = wo[(wo["topic_id"] == t) & (wo["order_name"] == "random")]["wss_95"].mean()
    if safe_wss >= rand_mean:
        wins += 1
assert wins >= 2, f"safest_to_riskiest wins on only {wins}/3 topics"
print("All acceptance criteria pass.")
```
