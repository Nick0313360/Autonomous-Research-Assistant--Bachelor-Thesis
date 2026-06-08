# Publication Figures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `cascade_rc/evaluation/figures.py` that generates three IEEE-publication-quality figures (PDF + PNG) deterministically from pre-computed baseline parquets, falling back to synthetic demo data when real data is absent.

**Architecture:** A single module with three `plot_figure<N>()` functions, three `_load_fig<N>_data()` loaders (real → synthetic fallback), three `_synthetic_figure<N>_data()` generators (fixed seed), and a `main()` CLI entry point. All randomness goes through `np.random.default_rng(0)`. PDF metadata is fixed to suppress timestamps so output bytes are reproducible.

**Tech Stack:** matplotlib, numpy, pandas, pathlib; reads `autostop_results.parquet`, `rlstop_results.parquet`, `scrc_results.parquet` from `artefacts/cascade_rc/baselines/`; writes to `artefacts/cascade_rc/figures/`.

---

## Data contracts

### Baseline parquet schema (AUTOSTOP, RLStop, SCRC-T, SCRC-I)

All four baseline drivers write parquets with this shared 8-column schema:

| column | dtype | notes |
|--------|-------|-------|
| `method` | object | e.g. `"autostop"`, `"rlstop"`, `"SCRC-I"`, `"SCRC-T"` |
| `topic_id` | object | e.g. `"CD008874"` |
| `target_recall` | float64 | ∈ {0.80, 0.90, 0.95, 1.0} |
| `examined` | int64 | docs screened |
| `recall_achieved` | float64 | empirical recall on test split |
| `wss_95` | float64 | WSS@target (nan if recall missed) |
| `wss_status` | object | `"ok"` | `"recall_target_missed"` | `"no_relevant_docs"` |
| `peak_rss_kb` | float64 | always nan |

**Mapping to figures:** `alpha = 1 - target_recall`; `fnr = 1 - recall_achieved`.

### CASCADE-RC sweep parquet (optional — synthesised if absent)

`artefacts/cascade_rc/baselines/cascade_rc_results.parquet`:

| column | dtype |
|--------|-------|
| `method` | object = `"CASCADE-RC"` |
| `topic_id` | object |
| `alpha` | float64 | LTT risk level ∈ {0.05,0.10,0.15,0.20,0.25,0.30} |
| `fnr` | float64 | empirical FNR on test split (always ≤ alpha) |
| `wss_95` | float64 |
| `wss_status` | object |

### CASCADE-RC routing sweep parquet (optional — synthesised if absent)

`artefacts/cascade_rc/baselines/cascade_rc_routing.parquet`:

| column | dtype |
|--------|-------|
| `alpha` | float64 |
| `cheap_reject` | float64 | fraction auto_reject |
| `auto_include` | float64 | fraction auto_accept |
| `llm` | float64 | fraction llm_escalate |
| `human` | float64 | fraction human_review |

---

## File Structure

- **Create:** `cascade_rc/evaluation/figures.py` — all plot logic
- **Create:** `cascade_rc/tests/test_figures.py` — smoke + determinism tests

---

## Task 1: File skeleton, constants, IEEE style helper

**Files:**
- Create: `cascade_rc/evaluation/figures.py`

- [ ] **Step 1: Write failing test for IEEE style application**

```python
# cascade_rc/tests/test_figures.py
"""Tests for cascade_rc.evaluation.figures."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # must be before any other matplotlib import

import matplotlib.pyplot as plt
import pytest

from cascade_rc.evaluation.figures import _apply_ieee_style, ALPHAS, METHODS


def test_ieee_style_sets_font_size() -> None:
    _apply_ieee_style()
    assert plt.rcParams["font.size"] == 8


def test_ieee_style_sets_serif() -> None:
    _apply_ieee_style()
    assert plt.rcParams["font.family"] == ["serif"]


def test_constants_coverage() -> None:
    assert len(ALPHAS) == 6
    assert "CASCADE-RC" in METHODS
    assert len(METHODS) == 5
```

Run: `pytest cascade_rc/tests/test_figures.py::test_ieee_style_sets_font_size -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 2: Write the file skeleton**

```python
# cascade_rc/evaluation/figures.py
"""Publication figures for CASCADE-RC systematic review screening.

Generates three IEEE-quality figures as both .pdf and .png.
Run:
    PYTHONHASHSEED=0 python -m cascade_rc.evaluation.figures \\
        --artefact-dir artefacts/cascade_rc
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEED = 0
ALPHAS: list[float] = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
RECALLS: list[float] = [0.80, 0.90, 0.95, 1.0]
METHODS: list[str] = ["CASCADE-RC", "AUTOSTOP", "RLStop", "SCRC-T", "SCRC-I"]
TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]
FIGSIZE = (3.5, 2.6)

_METHOD_COLORS: dict[str, str] = {
    "CASCADE-RC": "#1f77b4",
    "AUTOSTOP":   "#ff7f0e",
    "RLStop":     "#2ca02c",
    "SCRC-T":     "#d62728",
    "SCRC-I":     "#9467bd",
}
_METHOD_MARKERS: dict[str, str] = {
    "CASCADE-RC": "o",
    "AUTOSTOP":   "s",
    "RLStop":     "^",
    "SCRC-T":     "D",
    "SCRC-I":     "v",
}

_ROUTING_LABELS = ["cheap-reject", "auto-include", "LLM-self-evident", "human"]
_ROUTING_COLS   = ["cheap_reject", "auto_include", "llm", "human"]
_ROUTING_COLORS = ["#aec7e8", "#98df8a", "#ffbb78", "#ff9896"]

_PDF_META: dict[str, str] = {
    "Creator":     "cascade_rc.evaluation.figures",
    "Title":       "",
    "Subject":     "",
    "Author":      "",
    "CreationDate": "",
    "ModDate":     "",
}


# ---------------------------------------------------------------------------
# Style helper
# ---------------------------------------------------------------------------

def _apply_ieee_style() -> None:
    """Apply IEEEtran-friendly matplotlib style in-place."""
    plt.rcParams.update(
        {
            "font.family":        "serif",
            "font.size":          8,
            "axes.titlesize":     8,
            "axes.labelsize":     8,
            "xtick.labelsize":    7,
            "ytick.labelsize":    7,
            "legend.fontsize":    6,
            "lines.linewidth":    1.0,
            "lines.markersize":   3.5,
            "axes.linewidth":     0.6,
            "grid.linewidth":     0.4,
            "grid.alpha":         0.4,
            "figure.dpi":         150,
            "savefig.bbox":       "tight",
            "savefig.pad_inches": 0.01,
        }
    )
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest cascade_rc/tests/test_figures.py -v`
Expected: all 3 PASS

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/evaluation/figures.py cascade_rc/tests/test_figures.py
git commit -m "feat(figures): skeleton + IEEE style + constants"
```

---

## Task 2: Synthetic data generators

**Files:**
- Modify: `cascade_rc/evaluation/figures.py`

- [ ] **Step 1: Write failing tests for synthetic data**

Add to `cascade_rc/tests/test_figures.py`:

```python
from cascade_rc.evaluation.figures import (
    _synthetic_figure1_data,
    _synthetic_figure2_data,
    _synthetic_figure3_data,
)


def test_synthetic_fig1_has_all_methods() -> None:
    rng = np.random.default_rng(0)
    df = _synthetic_figure1_data(rng)
    assert set(df["method"].unique()) == set(METHODS)


def test_synthetic_fig1_cascade_rc_below_diagonal() -> None:
    import numpy as np
    rng = np.random.default_rng(0)
    df = _synthetic_figure1_data(rng)
    crc = df[df["method"] == "CASCADE-RC"]
    assert (crc["fnr"].values <= crc["alpha"].values + 1e-9).all(), \
        "CASCADE-RC FNR must not exceed alpha (validity guarantee)"


def test_synthetic_fig2_has_all_methods() -> None:
    import numpy as np
    rng = np.random.default_rng(0)
    df = _synthetic_figure2_data(rng)
    assert set(df["method"].unique()) == set(METHODS)


def test_synthetic_fig3_fractions_sum_to_one() -> None:
    import numpy as np
    rng = np.random.default_rng(0)
    df = _synthetic_figure3_data(rng)
    totals = df[["cheap_reject", "auto_include", "llm", "human"]].sum(axis=1)
    np.testing.assert_allclose(totals.values, 1.0, atol=1e-9)
```

Run: `pytest cascade_rc/tests/test_figures.py -k synthetic -v`
Expected: FAIL with ImportError

- [ ] **Step 2: Implement synthetic generators**

Add after `_apply_ieee_style()` in `figures.py`:

```python
# ---------------------------------------------------------------------------
# Synthetic data generators (deterministic, SEED=0)
# ---------------------------------------------------------------------------

def _synthetic_figure1_data(rng: np.random.Generator) -> pd.DataFrame:
    """Figure 1 synthetic: FNR vs alpha per method, CASCADE-RC below diagonal."""
    rows: list[dict] = []
    for method in METHODS:
        # baselines only have data at alphas matching their target_recall grid
        alphas = ALPHAS if method == "CASCADE-RC" else [0.05, 0.10, 0.20]
        for alpha in alphas:
            for topic in TOPICS:
                if method == "CASCADE-RC":
                    # validity guarantee: fnr < alpha
                    fnr = float(alpha * rng.uniform(0.50, 0.95))
                    wss = float(rng.uniform(0.35, 0.65))
                else:
                    # baselines can cross diagonal
                    noise = float(rng.normal(0.0, 0.025))
                    fnr = float(np.clip(alpha + noise, 0.0, 1.0))
                    wss = float(rng.uniform(0.20, 0.60))
                rows.append(
                    {"method": method, "topic_id": topic,
                     "alpha": alpha, "fnr": fnr, "wss": wss}
                )
    return pd.DataFrame(rows)


def _synthetic_figure2_data(rng: np.random.Generator) -> pd.DataFrame:
    """Figure 2 synthetic: WSS vs target_recall per method."""
    rows: list[dict] = []
    _wss_base = {
        "CASCADE-RC": 0.60, "AUTOSTOP": 0.50,
        "RLStop": 0.45, "SCRC-T": 0.42, "SCRC-I": 0.40,
    }
    for method in METHODS:
        base = _wss_base[method]
        for recall in RECALLS:
            for topic in TOPICS:
                # WSS generally decreases as target recall increases
                penalty = (recall - 0.80) * 0.8
                wss = float(np.clip(base - penalty + rng.normal(0.0, 0.03), 0.0, 1.0))
                rows.append(
                    {"method": method, "topic_id": topic,
                     "target_recall": recall, "wss": wss}
                )
    return pd.DataFrame(rows)


def _synthetic_figure3_data(rng: np.random.Generator) -> pd.DataFrame:
    """Figure 3 synthetic: routing fractions vs alpha for CASCADE-RC.

    As alpha tightens (decreases), cheap-reject shrinks, human grows.
    """
    rows: list[dict] = []
    for alpha in ALPHAS:
        # At alpha=0.30: lots of cheap-reject, little human
        # At alpha=0.05: human fraction grows, cheap-reject shrinks
        tightness = 1.0 - (alpha / 0.30)  # 0 at alpha=0.30, ~0.83 at alpha=0.05
        base_reject  = 0.55 - tightness * 0.30
        base_accept  = 0.25 - tightness * 0.05
        base_llm     = 0.10 + tightness * 0.05
        base_human   = 0.10 + tightness * 0.30
        noise = rng.normal(0.0, 0.01, 4)
        fracs = np.array([base_reject, base_accept, base_llm, base_human]) + noise
        fracs = np.clip(fracs, 0.01, None)
        fracs /= fracs.sum()
        rows.append(
            {
                "alpha":        alpha,
                "cheap_reject": float(fracs[0]),
                "auto_include": float(fracs[1]),
                "llm":          float(fracs[2]),
                "human":        float(fracs[3]),
            }
        )
    return pd.DataFrame(rows)
```

- [ ] **Step 3: Run tests**

Run: `pytest cascade_rc/tests/test_figures.py -k synthetic -v`
Expected: all 4 PASS

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/evaluation/figures.py cascade_rc/tests/test_figures.py
git commit -m "feat(figures): synthetic data generators for all three figures"
```

---

## Task 3: Real data loaders

**Files:**
- Modify: `cascade_rc/evaluation/figures.py`

These functions attempt to read real parquets, falling back to the synthetic generators.

- [ ] **Step 1: Write failing tests for loaders**

Add to `cascade_rc/tests/test_figures.py`:

```python
import tempfile
from pathlib import Path
from cascade_rc.evaluation.figures import _load_fig1_data, _load_fig2_data, _load_fig3_data


def test_loaders_fall_back_to_synthetic_when_no_parquets(tmp_path: Path) -> None:
    df1 = _load_fig1_data(tmp_path)
    assert set(df1["method"].unique()) == set(METHODS)

    df2 = _load_fig2_data(tmp_path)
    assert set(df2["method"].unique()) == set(METHODS)

    df3 = _load_fig3_data(tmp_path)
    assert set(df3["alpha"].unique()) == set(ALPHAS)


def test_loaders_use_real_autostop_parquet(tmp_path: Path) -> None:
    import numpy as np
    baseline_dir = tmp_path / "baselines"
    baseline_dir.mkdir()
    # write a minimal autostop parquet
    rows = [
        {"method": "autostop", "topic_id": "CD008874",
         "target_recall": 0.95, "examined": 100,
         "recall_achieved": 0.97, "wss_95": 0.42,
         "wss_status": "ok", "peak_rss_kb": float("nan")}
    ]
    pd.DataFrame(rows).to_parquet(baseline_dir / "autostop_results.parquet", index=False)
    df = _load_fig1_data(tmp_path)
    autostop_rows = df[df["method"] == "AUTOSTOP"]
    assert len(autostop_rows) >= 1
    assert float(autostop_rows.iloc[0]["alpha"]) == pytest.approx(0.05)
```

Run: `pytest cascade_rc/tests/test_figures.py -k loaders -v`
Expected: FAIL with ImportError

- [ ] **Step 2: Implement loaders**

Add after the synthetic generators in `figures.py`:

```python
# ---------------------------------------------------------------------------
# Real data loaders (fall back to synthetic)
# ---------------------------------------------------------------------------

def _normalise_method_name(raw: str) -> str:
    """Map parquet method strings to display names."""
    _MAP = {
        "autostop": "AUTOSTOP",
        "rlstop":   "RLStop",
        "SCRC-I":   "SCRC-I",
        "SCRC-T":   "SCRC-T",
        "cascade_rc": "CASCADE-RC",
        "CASCADE-RC": "CASCADE-RC",
    }
    return _MAP.get(raw, raw)


def _load_fig1_data(artefact_dir: Path) -> pd.DataFrame:
    """Load FNR-vs-alpha data; fall back to synthetic when parquets absent."""
    rng = np.random.default_rng(SEED)
    baseline_dir = artefact_dir / "baselines"
    frames: list[pd.DataFrame] = []

    # --- baseline parquets ---
    _BASELINE_FILES = {
        "autostop_results.parquet": None,
        "rlstop_results.parquet":   None,
        "scrc_results.parquet":     None,
    }
    for fname in _BASELINE_FILES:
        path = baseline_dir / fname
        if not path.exists():
            continue
        raw = pd.read_parquet(path)
        sub = pd.DataFrame(
            {
                "method":   raw["method"].map(_normalise_method_name),
                "topic_id": raw["topic_id"],
                "alpha":    1.0 - raw["target_recall"].astype(float),
                "fnr":      1.0 - raw["recall_achieved"].astype(float),
                "wss":      raw["wss_95"].astype(float),
            }
        )
        frames.append(sub)

    # --- CASCADE-RC sweep parquet ---
    crc_path = baseline_dir / "cascade_rc_results.parquet"
    if crc_path.exists():
        raw = pd.read_parquet(crc_path)
        sub = pd.DataFrame(
            {
                "method":   "CASCADE-RC",
                "topic_id": raw["topic_id"],
                "alpha":    raw["alpha"].astype(float),
                "fnr":      raw["fnr"].astype(float),
                "wss":      raw["wss_95"].astype(float),
            }
        )
        frames.append(sub)

    if not frames:
        return _synthetic_figure1_data(rng)

    df = pd.concat(frames, ignore_index=True)
    # synthetic fill for any missing method
    synth = _synthetic_figure1_data(rng)
    present = set(df["method"].unique())
    missing = [m for m in METHODS if m not in present]
    if missing:
        df = pd.concat(
            [df, synth[synth["method"].isin(missing)]], ignore_index=True
        )
    return df


def _load_fig2_data(artefact_dir: Path) -> pd.DataFrame:
    """Load WSS-vs-recall data; fall back to synthetic when parquets absent."""
    rng = np.random.default_rng(SEED)
    baseline_dir = artefact_dir / "baselines"
    frames: list[pd.DataFrame] = []

    for fname in [
        "autostop_results.parquet",
        "rlstop_results.parquet",
        "scrc_results.parquet",
    ]:
        path = baseline_dir / fname
        if not path.exists():
            continue
        raw = pd.read_parquet(path)
        sub = pd.DataFrame(
            {
                "method":        raw["method"].map(_normalise_method_name),
                "topic_id":      raw["topic_id"],
                "target_recall": raw["target_recall"].astype(float),
                "wss":           raw["wss_95"].astype(float),
            }
        )
        frames.append(sub)

    crc_path = baseline_dir / "cascade_rc_results.parquet"
    if crc_path.exists():
        raw = pd.read_parquet(crc_path)
        sub = pd.DataFrame(
            {
                "method":        "CASCADE-RC",
                "topic_id":      raw["topic_id"],
                "target_recall": 1.0 - raw["alpha"].astype(float),
                "wss":           raw["wss_95"].astype(float),
            }
        )
        frames.append(sub)

    if not frames:
        return _synthetic_figure2_data(rng)

    df = pd.concat(frames, ignore_index=True)
    synth = _synthetic_figure2_data(rng)
    present = set(df["method"].unique())
    missing = [m for m in METHODS if m not in present]
    if missing:
        df = pd.concat(
            [df, synth[synth["method"].isin(missing)]], ignore_index=True
        )
    return df


def _load_fig3_data(artefact_dir: Path) -> pd.DataFrame:
    """Load cascade routing sweep; fall back to synthetic."""
    rng = np.random.default_rng(SEED)
    path = artefact_dir / "baselines" / "cascade_rc_routing.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return _synthetic_figure3_data(rng)
```

- [ ] **Step 3: Run tests**

Run: `pytest cascade_rc/tests/test_figures.py -k loaders -v`
Expected: all 2 PASS

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/evaluation/figures.py cascade_rc/tests/test_figures.py
git commit -m "feat(figures): real data loaders with synthetic fallback"
```

---

## Task 4: Plot functions

**Files:**
- Modify: `cascade_rc/evaluation/figures.py`

- [ ] **Step 1: Write failing tests for plot functions**

Add to `cascade_rc/tests/test_figures.py`:

```python
from cascade_rc.evaluation.figures import plot_figure1, plot_figure2, plot_figure3


def test_plot_figure1_creates_pdf_and_png(tmp_path: Path) -> None:
    import numpy as np
    rng = np.random.default_rng(0)
    from cascade_rc.evaluation.figures import _synthetic_figure1_data
    df = _synthetic_figure1_data(rng)
    plot_figure1(df, tmp_path)
    assert (tmp_path / "figure1_risk_validity.pdf").exists()
    assert (tmp_path / "figure1_risk_validity.png").exists()


def test_plot_figure2_creates_pdf_and_png(tmp_path: Path) -> None:
    import numpy as np
    rng = np.random.default_rng(0)
    from cascade_rc.evaluation.figures import _synthetic_figure2_data
    df = _synthetic_figure2_data(rng)
    plot_figure2(df, tmp_path)
    assert (tmp_path / "figure2_wss_efficiency.pdf").exists()
    assert (tmp_path / "figure2_wss_efficiency.png").exists()


def test_plot_figure3_creates_pdf_and_png(tmp_path: Path) -> None:
    import numpy as np
    rng = np.random.default_rng(0)
    from cascade_rc.evaluation.figures import _synthetic_figure3_data
    df = _synthetic_figure3_data(rng)
    plot_figure3(df, tmp_path)
    assert (tmp_path / "figure3_escalation.pdf").exists()
    assert (tmp_path / "figure3_escalation.png").exists()
```

Run: `pytest cascade_rc/tests/test_figures.py -k plot_figure -v`
Expected: FAIL with ImportError

- [ ] **Step 2: Implement Figure 1**

Add to `figures.py` after the loaders:

```python
# ---------------------------------------------------------------------------
# Plot functions
# ---------------------------------------------------------------------------

def _save(fig: "plt.Figure", out_dir: Path, stem: str) -> None:
    """Save figure as both PDF (fixed metadata) and PNG."""
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{stem}.pdf", format="pdf", metadata=_PDF_META)
    fig.savefig(out_dir / f"{stem}.png", format="png")
    plt.close(fig)


def plot_figure1(df: pd.DataFrame, out_dir: Path) -> None:
    """Figure 1: Risk-control validity (empirical FNR vs target alpha).

    One line per method; diagonal y=x reference; shaded ±1 SE band per method.
    CASCADE-RC must sit on or below the diagonal.
    """
    _apply_ieee_style()
    fig, ax = plt.subplots(figsize=FIGSIZE)

    # diagonal reference
    ax.plot([0, 0.35], [0, 0.35], color="black", linewidth=0.8,
            linestyle="--", label="y = x", zorder=1)

    for method in METHODS:
        sub = df[df["method"] == method]
        if sub.empty:
            continue
        # average FNR per alpha across topics
        agg = (
            sub.groupby("alpha")["fnr"]
            .agg(mean="mean", std="std", count="count")
            .reset_index()
        )
        agg["se"] = agg["std"] / np.sqrt(agg["count"].clip(lower=1))
        agg = agg.sort_values("alpha")
        c = _METHOD_COLORS[method]
        m = _METHOD_MARKERS[method]
        ax.plot(
            agg["alpha"], agg["mean"],
            color=c, marker=m, label=method, zorder=3,
        )
        ax.fill_between(
            agg["alpha"],
            agg["mean"] - agg["se"],
            agg["mean"] + agg["se"],
            color=c, alpha=0.15, zorder=2,
        )

    ax.set_xlabel(r"Target risk $\alpha$")
    ax.set_ylabel("Empirical FNR")
    ax.set_xlim(0.02, 0.33)
    ax.set_ylim(0.0, 0.35)
    ax.set_xticks(ALPHAS)
    ax.grid(True)
    ax.legend(loc="upper left", ncol=1, framealpha=0.7)
    fig.tight_layout(pad=0.3)
    _save(fig, out_dir, "figure1_risk_validity")
```

- [ ] **Step 3: Implement Figure 2**

```python
def plot_figure2(df: pd.DataFrame, out_dir: Path) -> None:
    """Figure 2: Efficiency-safety trade-off (WSS vs target recall).

    One line per method; higher WSS = more work saved = more efficient.
    """
    _apply_ieee_style()
    fig, ax = plt.subplots(figsize=FIGSIZE)

    for method in METHODS:
        sub = df[df["method"] == method]
        if sub.empty:
            continue
        agg = (
            sub.groupby("target_recall")["wss"]
            .agg(mean="mean", std="std", count="count")
            .reset_index()
        )
        agg["se"] = agg["std"] / np.sqrt(agg["count"].clip(lower=1))
        agg = agg.sort_values("target_recall")
        c = _METHOD_COLORS[method]
        m = _METHOD_MARKERS[method]
        ax.plot(
            agg["target_recall"], agg["mean"],
            color=c, marker=m, label=method,
        )
        ax.fill_between(
            agg["target_recall"],
            agg["mean"] - agg["se"],
            agg["mean"] + agg["se"],
            color=c, alpha=0.15,
        )

    ax.set_xlabel("Target recall")
    ax.set_ylabel("WSS@target")
    ax.set_xlim(0.77, 1.03)
    ax.set_ylim(0.0, 0.75)
    ax.set_xticks(RECALLS)
    ax.grid(True)
    ax.legend(loc="upper right", ncol=1, framealpha=0.7)
    fig.tight_layout(pad=0.3)
    _save(fig, out_dir, "figure2_wss_efficiency")
```

- [ ] **Step 4: Implement Figure 3**

```python
def plot_figure3(df: pd.DataFrame, out_dir: Path) -> None:
    """Figure 3: Cascade escalation dynamics (stacked area, X = alpha).

    Shows how the cascade reallocates effort as alpha tightens.
    cheap-reject | auto-include | LLM-self-evident | human
    """
    _apply_ieee_style()
    fig, ax = plt.subplots(figsize=FIGSIZE)

    df_sorted = df.sort_values("alpha")
    x = df_sorted["alpha"].to_numpy()
    ys = [df_sorted[col].to_numpy() for col in _ROUTING_COLS]

    ax.stackplot(
        x, *ys,
        labels=_ROUTING_LABELS,
        colors=_ROUTING_COLORS,
        alpha=0.85,
    )

    ax.set_xlabel(r"Target risk $\alpha$")
    ax.set_ylabel("Fraction of corpus")
    ax.set_xlim(ALPHAS[0], ALPHAS[-1])
    ax.set_ylim(0.0, 1.0)
    ax.set_xticks(ALPHAS)
    ax.grid(True, axis="y")
    # legend outside to save space
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.28),
        ncol=2,
        framealpha=0.7,
    )
    fig.tight_layout(pad=0.3)
    _save(fig, out_dir, "figure3_escalation")
```

- [ ] **Step 5: Run tests**

Run: `pytest cascade_rc/tests/test_figures.py -k plot_figure -v`
Expected: all 3 PASS

- [ ] **Step 6: Commit**

```bash
git add cascade_rc/evaluation/figures.py cascade_rc/tests/test_figures.py
git commit -m "feat(figures): implement plot_figure1/2/3 with IEEE style"
```

---

## Task 5: `main()` entry point, end-to-end test, determinism check

**Files:**
- Modify: `cascade_rc/evaluation/figures.py`
- Modify: `cascade_rc/tests/test_figures.py`

- [ ] **Step 1: Write failing end-to-end test**

Add to `cascade_rc/tests/test_figures.py`:

```python
import hashlib
import subprocess
import sys


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def test_main_produces_six_artefacts(tmp_path: Path) -> None:
    from cascade_rc.evaluation.figures import main
    main(artefact_dir=tmp_path)
    expected_stems = [
        "figure1_risk_validity",
        "figure2_wss_efficiency",
        "figure3_escalation",
    ]
    fig_dir = tmp_path / "figures"
    for stem in expected_stems:
        assert (fig_dir / f"{stem}.pdf").exists(), f"{stem}.pdf missing"
        assert (fig_dir / f"{stem}.png").exists(), f"{stem}.png missing"


def test_main_is_deterministic(tmp_path: Path) -> None:
    from cascade_rc.evaluation.figures import main
    out1 = tmp_path / "run1"
    out2 = tmp_path / "run2"
    main(artefact_dir=out1)
    main(artefact_dir=out2)
    for stem in ["figure1_risk_validity", "figure2_wss_efficiency", "figure3_escalation"]:
        for ext in ["png"]:   # PNG is deterministic; PDF may differ in metadata
            p1 = out1 / "figures" / f"{stem}.{ext}"
            p2 = out2 / "figures" / f"{stem}.{ext}"
            assert _md5(p1) == _md5(p2), f"{stem}.{ext} is not deterministic"
```

Run: `pytest cascade_rc/tests/test_figures.py -k main -v`
Expected: FAIL with ImportError

- [ ] **Step 2: Implement `main()`**

Add to end of `figures.py`:

```python
# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(artefact_dir: Path = Path("artefacts/cascade_rc")) -> None:
    """Generate all three publication figures.

    Args:
        artefact_dir: root artefact directory; reads from <artefact_dir>/baselines/,
                      writes to <artefact_dir>/figures/.
    """
    os.environ.setdefault("PYTHONHASHSEED", "0")
    artefact_dir = Path(artefact_dir)
    out_dir = artefact_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    plot_figure1(_load_fig1_data(artefact_dir), out_dir)
    plot_figure2(_load_fig2_data(artefact_dir), out_dir)
    plot_figure3(_load_fig3_data(artefact_dir), out_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artefact-dir",
        type=Path,
        default=Path("artefacts/cascade_rc"),
        help="Root artefact directory (default: artefacts/cascade_rc)",
    )
    args = parser.parse_args()
    main(artefact_dir=args.artefact_dir)
```

- [ ] **Step 3: Run all tests**

Run: `pytest cascade_rc/tests/test_figures.py -v`
Expected: all tests PASS

- [ ] **Step 4: Smoke-run the script end-to-end**

```bash
cd /path/to/systematic-review-system
PYTHONHASHSEED=0 python -m cascade_rc.evaluation.figures --artefact-dir artefacts/cascade_rc
ls artefacts/cascade_rc/figures/
```

Expected output:
```
figure1_risk_validity.pdf  figure1_risk_validity.png
figure2_wss_efficiency.pdf  figure2_wss_efficiency.png
figure3_escalation.pdf  figure3_escalation.png
```

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/evaluation/figures.py cascade_rc/tests/test_figures.py
git commit -m "feat(figures): main() entry point + determinism test (Prompt 12.1)"
```

---

## Self-Review

**Spec coverage:**
- ✅ Figure 1: FNR vs α, one line per method, diagonal, ±1 SE shaded band
- ✅ Figure 2: WSS vs target_recall, one line per method
- ✅ Figure 3: stacked area, routing fractions vs α
- ✅ IEEE style: figsize=(3.5, 2.6), font.family='serif', font.size=8
- ✅ Save both .pdf and .png
- ✅ Output to artefacts/cascade_rc/figures/
- ✅ Deterministic (PYTHONHASHSEED=0, np.random.default_rng(0))
- ✅ CASCADE-RC below diagonal in synthetic data (validity illustration)
- ✅ Baselines can cross diagonal (illustrating absence of certificate)

**Placeholder scan:** No TBDs or TODOs — all code blocks are complete.

**Type consistency:**
- `_load_fig1_data`, `_load_fig2_data`, `_load_fig3_data`: all take `Path`, return `pd.DataFrame` ✅
- `plot_figure1/2/3`: all take `(pd.DataFrame, Path)` → None ✅
- `_synthetic_figure1/2/3_data`: all take `np.random.Generator` → `pd.DataFrame` ✅
- Column names consistent throughout: `alpha`, `fnr`, `wss`, `target_recall` ✅
