# Prompt 8.1 — Evaluation Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `cascade_rc/evaluation/metrics.py` with four pure metric functions and a CLI entry point (`python -m cascade_rc.evaluation.metrics --topic CD008874`) that emits a single JSON line with `wss95`, `llm_volume`, `slack_ratio_mean`, `slack_ratio_std`, and `status`.

**Architecture:** Pure functions in `metrics.py` are importable without side effects. The CLI derives per-document routing from the scored parquet + certified θ̂, writes a routing parquet as a side-effect, then calls each metric. `CertificationResult` gains a `slack_mat` field (pkl-only) so `bootstrap_eta_upper` reads precomputed slacks from disk without recomputing. `tar_eval_wrapper.py` is a thin subprocess wrapper around a vendored CLEF evaluation script (BSD-3/MIT).

**Tech Stack:** numpy 1.26.4, pandas 2.2.2, pytest 8.2.2, subprocess (stdlib), json (stdlib)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `cascade_rc/certificates/store.py` | Add `slack_mat: np.ndarray` field to `CertificationResult` |
| Modify | `cascade_rc/calibration/main_calibrate.py` | Pass `slack_mat=slack_mat` when constructing `CertificationResult` |
| Modify | `cascade_rc/config.py` | Add `delta_bootstrap: float = 0.05` to `LTTBudget` |
| Create | `cascade_rc/evaluation/__init__.py` | Package stub (empty) |
| Create | `cascade_rc/evaluation/metrics.py` | All four pure functions + `_derive_routing` + `main()` |
| Create | `cascade_rc/evaluation/tar_eval_wrapper.py` | Subprocess wrapper for vendored CLEF script |
| Create | `cascade_rc/baselines/__init__.py` | Package stub (empty) |
| Create | `cascade_rc/baselines/tar_eval_vendor/tar_eval.py` | Vendored CLEF script (committed) |
| Create | `cascade_rc/baselines/tar_eval_vendor/measures/` | Vendored CLEF measure modules |
| Create | `cascade_rc/baselines/tar_eval_vendor/VENDORED_FROM` | SHA + source URL + license note |
| Create | `cascade_rc/tests/test_metrics.py` | TDD tests for all four metric functions |

---

### Task 1: Foundations — `slack_mat` field, `delta_bootstrap` config, package stubs

**Files:**
- Modify: `cascade_rc/certificates/store.py`
- Modify: `cascade_rc/calibration/main_calibrate.py`
- Modify: `cascade_rc/config.py`
- Create: `cascade_rc/evaluation/__init__.py`
- Create: `cascade_rc/baselines/__init__.py`

- [ ] **Step 1: Add `slack_mat` field to `CertificationResult`**

In `cascade_rc/certificates/store.py`, replace the dataclass definition (lines 13–26) with:

```python
@dataclass
class CertificationResult:
    topic: str
    status: str                        # "certified" | "abstained"
    abstain_reason: str | None
    m_plus: int
    theta_hat: np.ndarray              # (3,) optimal θ̂ = (λ_lo, λ_hi, τ_SE)
    lambda_hat_mask: np.ndarray        # (G,) bool; True = certified
    theta_grid: np.ndarray             # (G, 3)
    eta_lcb_grid: np.ndarray           # (G,) η̂⁻⋆
    r_hat_grid: np.ndarray             # (G,) R̂
    p_hb_grid: np.ndarray             # (G,) p_HB
    alpha_dagger_grid: np.ndarray      # (G,) α†
    slack_mat: np.ndarray              # (G, m_plus) — pkl only, excluded from JSON
    config_snapshot: dict
    timestamp: str                     # ISO-8601
```

The JSON summary block in `CertificateStore.save()` does **not** reference `slack_mat` — verify the `summary` dict in that method and confirm it has no reference to the new field (it doesn't, so no further change to `save()` is needed).

- [ ] **Step 2: Wire `slack_mat` into `main_calibrate.py`**

In `cascade_rc/calibration/main_calibrate.py`, find the `CertificationResult(...)` call (~line 209) and add the `slack_mat` keyword argument:

```python
result = CertificationResult(
    topic=topic_id,
    status="certified",
    abstain_reason=None,
    m_plus=m_plus,
    theta_hat=theta_hat,
    lambda_hat_mask=lambda_hat_mask,
    theta_grid=theta_g,
    eta_lcb_grid=eta_lcb,
    r_hat_grid=R_hat,
    p_hb_grid=p_hb,
    alpha_dagger_grid=alpha_dagger,
    slack_mat=slack_mat,
    config_snapshot={
        "alpha": alpha,
        "delta_eta": delta_eta,
        "delta_LTT": delta_ltt,
        "K": K,
        "c_human": c_human,
        "c_llm": c_llm,
    },
    timestamp=datetime.now(timezone.utc).isoformat(),
)
```

`slack_mat` is already in scope at this point (computed at line ~170 as `slack_mat = slack_tensor(...)`).

- [ ] **Step 3: Add `delta_bootstrap` to `LTTBudget`**

In `cascade_rc/config.py`, add `delta_bootstrap` after `c_llm` in the `LTTBudget` class:

```python
class LTTBudget(BaseModel):
    alpha: float = 0.10
    delta_total: float = 0.10
    delta_eta: float = 0.03
    delta_LTT: float = 0.07
    K: int = 20
    B: int = 5
    ensemble_temperature: float = 0.7
    N_min_formula: str = "ceil(ln(1/delta_LTT)/(-ln(1-alpha)))"
    c_human: float = 5.0
    c_llm: float = 0.001
    delta_bootstrap: float = 0.05
```

- [ ] **Step 4: Create package stubs**

```bash
touch cascade_rc/evaluation/__init__.py
touch cascade_rc/baselines/__init__.py
```

- [ ] **Step 5: Run existing tests — confirm no regressions**

```bash
cd systematic-review-system
python -m pytest cascade_rc/tests/ -x -q
```

Expected: all previously passing tests still pass. The `CertificationResult` field addition is backward-incompatible with existing pickled certs on disk, but no tests load real certs from disk.

- [ ] **Step 6: Commit**

```bash
git add cascade_rc/certificates/store.py \
        cascade_rc/calibration/main_calibrate.py \
        cascade_rc/config.py \
        cascade_rc/evaluation/__init__.py \
        cascade_rc/baselines/__init__.py
git commit -m "feat(cert): add slack_mat to CertificationResult; add delta_bootstrap to LTTBudget"
```

---

### Task 2: `wss_at_recall` — TDD

**Files:**
- Create: `cascade_rc/tests/test_metrics.py`
- Create: `cascade_rc/evaluation/metrics.py` (partial — `wss_at_recall` only)

- [ ] **Step 1: Write the failing tests**

Create `cascade_rc/tests/test_metrics.py`:

```python
"""Tests for cascade_rc/evaluation/metrics.py."""
from __future__ import annotations

import numpy as np
import pytest

from cascade_rc.evaluation.metrics import wss_at_recall


# ---------------------------------------------------------------------------
# wss_at_recall
# ---------------------------------------------------------------------------

def test_wss_at_recall_hand_computed() -> None:
    """10-doc corpus, 3 positives, 5 screened (all positives in screened set).

    TN=4, FN=0, N=10, recall=1.0.
    WSS@0.95 = (4+0)/10 - (1-0.95) = 0.40 - 0.05 = 0.35
    """
    y_true      = np.array([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    predictions = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
    result = wss_at_recall(predictions, y_true, target_recall=0.95)
    assert result["status"] == "ok"
    assert result["achieved_recall"] == pytest.approx(1.0)
    assert result["wss"] == pytest.approx(0.35, abs=1e-9)


def test_wss_at_recall_monotone_in_target() -> None:
    """For fixed predictions with achieved_recall=1.0, wss increases with target_recall."""
    y_true      = np.array([1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
    predictions = np.array([1, 1, 1, 1, 1, 1, 0, 0, 0, 0])  # recall=5/5=1.0
    wss_70 = wss_at_recall(predictions, y_true, target_recall=0.70)["wss"]
    wss_95 = wss_at_recall(predictions, y_true, target_recall=0.95)["wss"]
    assert wss_70 < wss_95


def test_wss_at_recall_recall_target_missed() -> None:
    """achieved_recall < target → status='recall_target_missed', wss=nan."""
    y_true      = np.array([1, 1, 1, 0, 0])
    predictions = np.array([1, 0, 0, 0, 0])  # recall=1/3 ≈ 0.33
    result = wss_at_recall(predictions, y_true, target_recall=0.95)
    assert result["status"] == "recall_target_missed"
    assert np.isnan(result["wss"])
    assert result["achieved_recall"] == pytest.approx(1.0 / 3.0, rel=1e-6)
```

- [ ] **Step 2: Run test to confirm FAIL**

```bash
python -m pytest cascade_rc/tests/test_metrics.py -x -q
```

Expected: `ImportError: cannot import name 'wss_at_recall'`

- [ ] **Step 3: Implement `wss_at_recall`**

Create `cascade_rc/evaluation/metrics.py`:

```python
"""Evaluation metrics for CASCADE-RC systematic review screening."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def wss_at_recall(
    predictions: np.ndarray,
    y_true: np.ndarray,
    target_recall: float = 0.95,
) -> dict:
    """Work Saved over Sampling at target recall (CLEF / Cohen 2006 formula).

    WSS@r = (TN + FN) / N - (1 - r), evaluated at the certified θ̂ routing.

    Returns:
        dict with keys:
            wss (float | nan): WSS value, or nan if recall target was missed.
            achieved_recall (float): recall of the given predictions.
            status (str): "ok" | "recall_target_missed" | "no_relevant_docs".
    """
    n_relevant = int(np.sum(y_true == 1))
    if n_relevant == 0:
        return {
            "wss": float("nan"),
            "achieved_recall": float("nan"),
            "status": "no_relevant_docs",
        }
    achieved = float(np.sum((predictions == 1) & (y_true == 1)) / n_relevant)
    if achieved < target_recall:
        return {
            "wss": float("nan"),
            "achieved_recall": achieved,
            "status": "recall_target_missed",
        }
    tn = int(np.sum((predictions == 0) & (y_true == 0)))
    fn = int(np.sum((predictions == 0) & (y_true == 1)))
    n = len(y_true)
    wss = (tn + fn) / n - (1.0 - target_recall)
    return {"wss": wss, "achieved_recall": achieved, "status": "ok"}
```

- [ ] **Step 4: Run tests — confirm PASS**

```bash
python -m pytest cascade_rc/tests/test_metrics.py -x -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/evaluation/metrics.py cascade_rc/tests/test_metrics.py
git commit -m "feat(metrics): implement wss_at_recall with TDD"
```

---

### Task 3: `abstention_rate` and `llm_query_volume` — TDD

**Files:**
- Modify: `cascade_rc/tests/test_metrics.py`
- Modify: `cascade_rc/evaluation/metrics.py`

- [ ] **Step 1: Write the failing tests**

Append to `cascade_rc/tests/test_metrics.py`:

```python
import pandas as pd
from cascade_rc.evaluation.metrics import abstention_rate, llm_query_volume


# ---------------------------------------------------------------------------
# abstention_rate
# ---------------------------------------------------------------------------

def test_abstention_rate_all_certified() -> None:
    certified = {
        "CD008874": {"status": "certified"},
        "CD012080": {"status": "certified"},
    }
    assert abstention_rate(certified) == pytest.approx(0.0)


def test_abstention_rate_mixed() -> None:
    certified = {
        "CD008874": {"status": "certified"},
        "CD012080": {"status": "abstained"},
        "CD011768": {"status": "abstained"},
        "CD011975": {"status": "certified"},
    }
    assert abstention_rate(certified) == pytest.approx(0.5)


def test_abstention_rate_empty_returns_nan() -> None:
    assert np.isnan(abstention_rate({}))


# ---------------------------------------------------------------------------
# llm_query_volume
# ---------------------------------------------------------------------------

def test_llm_query_volume_counts() -> None:
    routing = pd.DataFrame({
        "pmid": ["1", "2", "3", "4", "5", "6"],
        "decision": [
            "auto_accept", "auto_reject", "auto_reject",
            "llm_escalate", "human_review", "human_review",
        ],
    })
    result = llm_query_volume(routing)
    assert result["auto_accept"] == 1
    assert result["auto_reject"] == 2
    assert result["llm_escalate"] == 1
    assert result["human_review"] == 2
    assert result["total"] == 6
    assert result["llm_fraction"] == pytest.approx(1.0 / 6.0)


def test_llm_query_volume_unknown_decision_raises() -> None:
    routing = pd.DataFrame({"pmid": ["1"], "decision": ["tier_4_special"]})
    with pytest.raises(ValueError, match="Unexpected decision values"):
        llm_query_volume(routing)
```

- [ ] **Step 2: Run tests to confirm FAIL**

```bash
python -m pytest cascade_rc/tests/test_metrics.py -x -q -k "abstention or llm_query"
```

Expected: `ImportError: cannot import name 'abstention_rate'`

- [ ] **Step 3: Implement `abstention_rate` and `llm_query_volume`**

Append to `cascade_rc/evaluation/metrics.py`:

```python
def abstention_rate(certified: dict[str, dict]) -> float:
    """Fraction of topics that abstained. Returns nan for empty input.

    Args:
        certified: mapping topic_id → {status: "certified"|"abstained", ...}.

    Returns:
        Float in [0, 1], or nan if certified is empty.
    """
    if not certified:
        return float("nan")
    n_abstained = sum(1 for v in certified.values() if v.get("status") == "abstained")
    return float(n_abstained / len(certified))


_VALID_DECISIONS: frozenset[str] = frozenset(
    {"auto_accept", "auto_reject", "llm_escalate", "human_review"}
)


def llm_query_volume(routing: pd.DataFrame) -> dict:
    """Aggregate routing decisions into a volume breakdown dict.

    Args:
        routing: DataFrame with columns {pmid: str, decision: str} where
                 decision ∈ {auto_accept, auto_reject, llm_escalate, human_review}.

    Returns:
        dict with keys auto_accept, auto_reject, llm_escalate, human_review,
        total (int), llm_fraction (float).

    Raises:
        ValueError: if any decision value is not in _VALID_DECISIONS.
    """
    unknown = set(routing["decision"].unique()) - _VALID_DECISIONS
    if unknown:
        raise ValueError(f"Unexpected decision values: {unknown!r}")
    counts = routing["decision"].value_counts().to_dict()
    total = len(routing)
    llm_escalate = counts.get("llm_escalate", 0)
    return {
        "auto_accept":  int(counts.get("auto_accept", 0)),
        "auto_reject":  int(counts.get("auto_reject", 0)),
        "llm_escalate": int(llm_escalate),
        "human_review": int(counts.get("human_review", 0)),
        "total": total,
        "llm_fraction": llm_escalate / total if total > 0 else 0.0,
    }
```

- [ ] **Step 4: Run tests — confirm PASS**

```bash
python -m pytest cascade_rc/tests/test_metrics.py -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/evaluation/metrics.py cascade_rc/tests/test_metrics.py
git commit -m "feat(metrics): implement abstention_rate and llm_query_volume with TDD"
```

---

### Task 4: `bootstrap_eta_upper` and `slack_ratio_diagnostic` — TDD

**Files:**
- Modify: `cascade_rc/tests/test_metrics.py`
- Modify: `cascade_rc/evaluation/metrics.py`

- [ ] **Step 1: Write the failing tests**

Append to `cascade_rc/tests/test_metrics.py`:

```python
from cascade_rc.evaluation.metrics import bootstrap_eta_upper, slack_ratio_diagnostic


# ---------------------------------------------------------------------------
# bootstrap_eta_upper
# ---------------------------------------------------------------------------

def test_bootstrap_eta_upper_shape() -> None:
    """Returns (G,) array for (G, m_plus) input."""
    rng = np.random.default_rng(0)
    G, m_plus = 5, 80
    slack_mat = rng.uniform(0.0, 0.3, size=(G, m_plus))
    upper = bootstrap_eta_upper(slack_mat, delta=0.05, B=500, seed=1)
    assert upper.shape == (G,)


def test_bootstrap_eta_upper_covers_sample_mean() -> None:
    """Bootstrap (1-delta) upper bound >= sample mean for all G rows (should hold always)."""
    rng = np.random.default_rng(42)
    G, m_plus = 4, 200
    slack_mat = rng.uniform(0.0, 0.3, size=(G, m_plus))
    upper = bootstrap_eta_upper(slack_mat, delta=0.05, B=2000, seed=0)
    sample_means = slack_mat.mean(axis=1)
    assert np.all(upper >= sample_means - 1e-9)


def test_bootstrap_eta_upper_deterministic() -> None:
    """Same seed yields identical result across two calls."""
    rng = np.random.default_rng(7)
    slack_mat = rng.uniform(0.0, 0.5, size=(3, 50))
    u1 = bootstrap_eta_upper(slack_mat, delta=0.10, B=200, seed=99)
    u2 = bootstrap_eta_upper(slack_mat, delta=0.10, B=200, seed=99)
    np.testing.assert_array_equal(u1, u2)


# ---------------------------------------------------------------------------
# slack_ratio_diagnostic
# ---------------------------------------------------------------------------

def test_slack_ratio_diagnostic_values() -> None:
    eta_lcb  = np.array([0.5, 0.8, 0.0])
    eta_boot = np.array([1.0, 1.0, 0.5])
    ratio = slack_ratio_diagnostic(eta_lcb, eta_boot)
    np.testing.assert_allclose(ratio, [0.5, 0.8, 0.0])


def test_slack_ratio_diagnostic_zero_denominator_gives_nan() -> None:
    """eta_boot_upper == 0 → nan (not a division error)."""
    eta_lcb  = np.array([0.5, 0.3])
    eta_boot = np.array([0.0, 1.0])
    ratio = slack_ratio_diagnostic(eta_lcb, eta_boot)
    assert np.isnan(ratio[0])
    assert ratio[1] == pytest.approx(0.3)
```

- [ ] **Step 2: Run tests to confirm FAIL**

```bash
python -m pytest cascade_rc/tests/test_metrics.py -x -q -k "bootstrap or slack_ratio"
```

Expected: `ImportError: cannot import name 'bootstrap_eta_upper'`

- [ ] **Step 3: Implement `bootstrap_eta_upper` and `slack_ratio_diagnostic`**

Append to `cascade_rc/evaluation/metrics.py`:

```python
def bootstrap_eta_upper(
    slack_mat: np.ndarray,
    delta: float,
    B: int = 1000,
    seed: int = 0,
) -> np.ndarray:
    """Bootstrap (1−delta) upper confidence bound on mean slack per grid point.

    Args:
        slack_mat: (G, m_plus) float64 from CertificationResult.slack_mat.
        delta:     Confidence level — use config.ltt.delta_bootstrap.
        B:         Number of bootstrap resamples (default 1000).
        seed:      RNG seed for reproducibility.

    Returns:
        (G,) array: for each grid point, the (1−delta)-quantile of B bootstrap means.
    """
    G, m_plus = slack_mat.shape
    rng = np.random.default_rng(seed)
    boot_means = np.empty((G, B), dtype=np.float64)
    for b in range(B):
        idx = rng.integers(0, m_plus, size=(G, m_plus))         # (G, m_plus)
        boot_means[:, b] = slack_mat[np.arange(G)[:, None], idx].mean(axis=1)
    return np.quantile(boot_means, 1.0 - delta, axis=1)         # (G,)


def slack_ratio_diagnostic(
    eta_lcb: np.ndarray,
    eta_boot_upper: np.ndarray,
) -> np.ndarray:
    """Element-wise tightness ratio η̂⁻⋆ / η̂⁺_boot (paper §9.4).

    Values ≈ 1: WSR LCB is tight relative to bootstrap estimate.
    Values << 1: bound is conservative.
    Returns nan where eta_boot_upper == 0.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(eta_boot_upper > 0.0, eta_lcb / eta_boot_upper, np.nan)
```

- [ ] **Step 4: Run all tests — confirm PASS**

```bash
python -m pytest cascade_rc/tests/test_metrics.py -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/evaluation/metrics.py cascade_rc/tests/test_metrics.py
git commit -m "feat(metrics): implement bootstrap_eta_upper and slack_ratio_diagnostic with TDD"
```

---

### Task 5: Vendor CLEF `tar_eval.py` and implement `tar_eval_wrapper.py`

**Files:**
- Create: `cascade_rc/baselines/tar_eval_vendor/` (directory)
- Create: `cascade_rc/evaluation/tar_eval_wrapper.py`

The CLEF-TAR `tar_eval.py` is at `scripts/tar_eval.py` in the `CLEF-TAR/tar` GitHub repo. It imports from a local `measures/` package (`measures.tar_rulers`, `measures.eval_measures`). All files must be vendored together. The output format is tab-delimited: `{topic_id}\t{metric_name}\t{value}` where value is a 3-decimal float.

- [ ] **Step 1: Clone and copy the vendored files**

```bash
# Set REPO to the absolute path of the systematic-review-system directory.
REPO="$(git -C . rev-parse --show-toplevel)/systematic-review-system"
# If running from inside systematic-review-system already: REPO="$(pwd)"

cd /tmp
git clone --depth=1 --filter=blob:none --sparse https://github.com/CLEF-TAR/tar.git clef_tar_tmp
cd clef_tar_tmp
git sparse-checkout set scripts

VENDOR="$REPO/cascade_rc/baselines/tar_eval_vendor"
mkdir -p "$VENDOR/measures"
cp scripts/tar_eval.py "$VENDOR/"
cp scripts/measures/eval_measures.py "$VENDOR/measures/"
cp scripts/measures/tar_rulers.py   "$VENDOR/measures/"
touch "$VENDOR/measures/__init__.py"

SHA=$(git rev-parse HEAD)
cat > "$VENDOR/VENDORED_FROM" <<EOF
Source:   https://github.com/CLEF-TAR/tar
Path:     scripts/tar_eval.py + scripts/measures/eval_measures.py + scripts/measures/tar_rulers.py
Commit:   $SHA
License:  See LICENSE in source repo. Verify license terms before distributing.
Vendored: $(date -I)
EOF

cd /tmp && rm -rf clef_tar_tmp
```

- [ ] **Step 2: Verify the vendored script imports cleanly**

```bash
cd cascade_rc/baselines/tar_eval_vendor
python tar_eval.py 2>&1 | head -3
```

Expected: a usage message or "missing arguments" error — NOT an `ImportError` or `ModuleNotFoundError`.

- [ ] **Step 3: Capture the actual output schema**

Create a minimal qrel + results file and run the script to observe exact metric key names:

```bash
echo "CD008874 0 12345678 1" > /tmp/test_eval.qrel
echo "CD008874 Q0 12345678 1 0.9 run1" > /tmp/test_eval.results
python cascade_rc/baselines/tar_eval_vendor/tar_eval.py \
    /tmp/test_eval.qrel /tmp/test_eval.results
```

Copy the exact metric names from stdout (second tab-delimited column of each line). Confirm whether recall is output as `r` or `recall`, and whether `wss_100`/`wss_95`/`norm_area` match. Update `REQUIRED_KEYS` in the next step to exactly match the observed keys.

- [ ] **Step 4: Implement `tar_eval_wrapper.py`**

Create `cascade_rc/evaluation/tar_eval_wrapper.py`.

The output format per source-code analysis is: `{topic_id}\t{metric_name}\t{value}`.
The measure classes emit these keys: `wss_100`, `wss_95`, `r` (recall), `norm_area`,
`loss_e`, `loss_r`, `loss_er`. Confirm exact names from Step 3 before finalizing
`REQUIRED_KEYS`.

```python
"""Subprocess wrapper for the vendored CLEF TAR evaluation script.

Output format: each line is {topic_id}\\t{metric_name}\\t{value} (3 decimal float).
The script requires two positional args: <qrel_file> <results_file>.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_VENDOR_SCRIPT: Path = (
    Path(__file__).parent.parent / "baselines" / "tar_eval_vendor" / "tar_eval.py"
)

# Keys confirmed by running the vendored script (Step 3 of Task 5).
# Source analysis: eval_measures.py emits "r" for recall, not "recall".
# Update this frozenset if Step 3 reveals different names.
REQUIRED_KEYS: frozenset[str] = frozenset({"wss_100", "wss_95", "r", "norm_area"})


def run_tar_eval(
    qrels_file: Path,
    results_file: Path,
    timeout: int = 300,
) -> dict[str, float]:
    """Run vendored CLEF tar_eval.py and return parsed metric dict.

    Captures both stdout and stderr. Logs stderr lines at WARNING level.
    Parses stdout by splitting on tab (3 fields per line: topic, metric, value).
    Returns aggregated metrics (last occurrence of each metric key wins,
    which corresponds to the overall aggregate printed last by TarAggRuler).

    Args:
        qrels_file:   Path to TREC-format qrel file.
        results_file: Path to TREC-format results file.
        timeout:      Max subprocess runtime in seconds.

    Returns:
        dict mapping metric_name → float.

    Raises:
        subprocess.TimeoutExpired: script exceeded timeout.
        RuntimeError: script exited non-zero.
        ValueError: REQUIRED_KEYS missing from parsed output.
    """
    proc = subprocess.run(
        ["python", str(_VENDOR_SCRIPT), str(qrels_file), str(results_file)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    for line in proc.stderr.splitlines():
        logger.warning("tar_eval stderr: %s", line)

    if proc.returncode != 0:
        raise RuntimeError(
            f"tar_eval.py exited {proc.returncode}:\n{proc.stderr[:500]}"
        )

    parsed: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 3:
            continue
        _topic_id, metric, value_str = parts
        try:
            parsed[metric] = float(value_str)
        except ValueError:
            continue

    missing = REQUIRED_KEYS - set(parsed)
    if missing:
        raise ValueError(
            f"tar_eval output missing required keys: {missing!r}\n"
            f"Got keys: {sorted(parsed)!r}\n"
            f"Raw stdout (first 500 chars):\n{proc.stdout[:500]}"
        )

    return parsed
```

- [ ] **Step 5: Smoke-test the wrapper**

```bash
python -c "
from pathlib import Path
from cascade_rc.evaluation.tar_eval_wrapper import run_tar_eval
import tempfile

with tempfile.NamedTemporaryFile('w', suffix='.qrel', delete=False) as q:
    q.write('CD008874 0 12345678 1\n')
    qrel_path = Path(q.name)

with tempfile.NamedTemporaryFile('w', suffix='.results', delete=False) as r:
    r.write('CD008874 Q0 12345678 1 0.9 run1\n')
    res_path = Path(r.name)

out = run_tar_eval(qrel_path, res_path)
print(out)
"
```

Expected: a dict printed with float values — no crash, no `ValueError` about missing keys. If `ValueError` fires, update `REQUIRED_KEYS` to match the actual keys observed in Step 3.

- [ ] **Step 6: Commit**

```bash
git add cascade_rc/baselines/tar_eval_vendor/ cascade_rc/evaluation/tar_eval_wrapper.py
git commit -m "feat(baselines): vendor CLEF tar_eval.py and implement subprocess wrapper"
```

---

### Task 6: CLI `main()` in `metrics.py`

**Files:**
- Modify: `cascade_rc/evaluation/metrics.py` (add `_derive_routing`, `_predictions_from_routing`, `main`)

- [ ] **Step 1: Add `_derive_routing` and `_predictions_from_routing`**

Append to `cascade_rc/evaluation/metrics.py`:

```python
_SCREENED_DECISIONS: frozenset[str] = frozenset(
    {"auto_accept", "llm_escalate", "human_review"}
)


def _derive_routing(df: pd.DataFrame, theta_hat: np.ndarray) -> pd.DataFrame:
    """Apply certified threshold θ̂ = (λ_lo, λ_hi, τ_SE) to produce a decision column.

    Args:
        df:        DataFrame with columns s (float) and u (float).
        theta_hat: (3,) array [λ_lo, λ_hi, τ_SE].

    Returns:
        Copy of df with column 'decision' ∈
        {auto_accept, auto_reject, llm_escalate, human_review}.
    """
    lam_lo = float(theta_hat[0])
    lam_hi = float(theta_hat[1])
    tau_se = float(theta_hat[2])

    s = df["s"].to_numpy(dtype=np.float64)
    u = df["u"].to_numpy(dtype=np.float64)

    decision = np.empty(len(df), dtype=object)
    decision[s < lam_lo] = "auto_reject"
    decision[s >= lam_hi] = "auto_accept"
    uncertain = (s >= lam_lo) & (s < lam_hi)
    decision[uncertain & (u >= tau_se)] = "llm_escalate"
    decision[uncertain & (u < tau_se)] = "human_review"

    out = df.copy()
    out["decision"] = decision
    return out


def _predictions_from_routing(routing: pd.DataFrame) -> np.ndarray:
    """Convert decision column to binary predictions: 1=screened, 0=skipped."""
    return routing["decision"].isin(_SCREENED_DECISIONS).to_numpy(dtype=np.int8)
```

- [ ] **Step 2: Add `main()`**

Append to `cascade_rc/evaluation/metrics.py`:

```python
def main() -> None:
    import argparse
    import json
    import sys

    from cascade_rc.certificates.store import CertificateStore
    from cascade_rc.config import CascadeRCConfig

    parser = argparse.ArgumentParser(
        description="CASCADE-RC per-topic evaluation metrics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--topic", required=True, help="Topic ID, e.g. CD008874")
    parser.add_argument(
        "--artefact-dir", type=Path, default=Path("artefacts/cascade_rc"),
        help="Root artefact directory (contains certificates/ and data/)",
    )
    parser.add_argument(
        "--calib-parquet", type=Path, default=None,
        help="Scored parquet (columns: pmid, s, u, y_abstract, llm_y_hat, is_calib). "
             "Default: <artefact-dir>/data/<topic>.parquet",
    )
    args = parser.parse_args()

    artefact_dir: Path = Path(args.artefact_dir)
    calib_parquet: Path = (
        args.calib_parquet or artefact_dir / "data" / f"{args.topic}.parquet"
    )

    cfg = CascadeRCConfig()
    cert = CertificateStore.load(args.topic, artefact_dir)

    df = pd.read_parquet(calib_parquet)
    df_test = df[df["is_calib"] == 0].reset_index(drop=True)

    routing_df = _derive_routing(df_test, cert.theta_hat)
    routing_dir = artefact_dir / "routing"
    routing_dir.mkdir(parents=True, exist_ok=True)
    routing_df[["pmid", "decision"]].to_parquet(
        routing_dir / f"{args.topic}.parquet", index=False
    )

    llm_vol = llm_query_volume(routing_df[["pmid", "decision"]])

    predictions = _predictions_from_routing(routing_df)
    y_true = df_test["y_abstract"].to_numpy(dtype=np.int8)
    wss_result = wss_at_recall(predictions, y_true, target_recall=0.95)

    eta_boot = bootstrap_eta_upper(
        cert.slack_mat, delta=cfg.ltt.delta_bootstrap, B=1000, seed=0
    )
    ratio = slack_ratio_diagnostic(cert.eta_lcb_grid, eta_boot)

    output = {
        "topic": args.topic,
        "status": cert.status,
        "wss95": wss_result,
        "llm_volume": llm_vol,
        "slack_ratio_mean": float(np.nanmean(ratio)),
        "slack_ratio_std": float(np.nanstd(ratio)),
    }
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify `--help` works**

```bash
python -m cascade_rc.evaluation.metrics --help
```

Expected: usage message listing `--topic`, `--artefact-dir`, `--calib-parquet`.

- [ ] **Step 4: Run all tests — confirm no regressions**

```bash
python -m pytest cascade_rc/tests/ -x -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/evaluation/metrics.py
git commit -m "feat(metrics): add CLI main() with routing derivation and JSON output"
```

---

### Task 7: Acceptance test with synthetic artefact

**Files:** No new files — manual smoke test of the acceptance criterion.

- [ ] **Step 1: Write and run the synthetic artefact script**

```bash
python - <<'EOF'
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from cascade_rc.certificates.store import CertificationResult, CertificateStore

rng = np.random.default_rng(0)
G, m_plus = 8, 30
topic = "CD008874"
artefact_dir = Path("/tmp/cascade_rc_acceptance")

theta_grid = np.array([
    [0.2, 0.8, 0.5],
    [0.3, 0.7, 0.5],
    [0.1, 0.9, 0.4],
    [0.2, 0.6, 0.6],
    [0.4, 0.8, 0.5],
    [0.3, 0.8, 0.3],
    [0.2, 0.7, 0.4],
    [0.1, 0.8, 0.6],
])

result = CertificationResult(
    topic=topic,
    status="certified",
    abstain_reason=None,
    m_plus=m_plus,
    theta_hat=np.array([0.2, 0.8, 0.5]),
    lambda_hat_mask=np.array([True, False, True, False, False, True, True, False]),
    theta_grid=theta_grid,
    eta_lcb_grid=rng.uniform(0.01, 0.05, G),
    r_hat_grid=rng.uniform(0.05, 0.15, G),
    p_hb_grid=rng.uniform(0.0, 0.1, G),
    alpha_dagger_grid=rng.uniform(0.10, 0.15, G),
    slack_mat=rng.uniform(0.0, 0.3, size=(G, m_plus)),
    config_snapshot={
        "alpha": 0.10, "delta_eta": 0.03, "delta_LTT": 0.07,
        "K": 20, "c_human": 5.0, "c_llm": 0.001,
    },
    timestamp=datetime.now(timezone.utc).isoformat(),
)
CertificateStore.save(topic, result, artefact_dir)

n_test = 40
df = pd.DataFrame({
    "pmid": [str(i) for i in range(n_test)],
    "s": rng.uniform(0.0, 1.0, n_test),
    "u": rng.uniform(0.0, 1.0, n_test),
    "y_abstract": rng.integers(0, 2, n_test).astype("int8"),
    "llm_y_hat": rng.integers(0, 2, n_test).astype("int8"),
    "is_calib": np.zeros(n_test, dtype="int8"),
})
(artefact_dir / "data").mkdir(parents=True, exist_ok=True)
df.to_parquet(artefact_dir / "data" / f"{topic}.parquet", index=False)
print("Synthetic artefacts written to", artefact_dir)
EOF
```

Expected: `Synthetic artefacts written to /tmp/cascade_rc_acceptance`

- [ ] **Step 2: Run the acceptance criterion command**

```bash
python -m cascade_rc.evaluation.metrics \
    --topic CD008874 \
    --artefact-dir /tmp/cascade_rc_acceptance
```

Expected: a single JSON line. Verify it contains all five top-level keys:
`topic`, `status`, `wss95`, `llm_volume`, `slack_ratio_mean`.

Example output shape (exact numbers will vary with the random seed):

```json
{"topic": "CD008874", "status": "certified", "wss95": {"wss": 0.35, "achieved_recall": 1.0, "status": "ok"}, "llm_volume": {"auto_accept": 10, "auto_reject": 12, "llm_escalate": 8, "human_review": 10, "total": 40, "llm_fraction": 0.2}, "slack_ratio_mean": 0.88, "slack_ratio_std": 0.04}
```

- [ ] **Step 3: Run the full test suite one final time**

```bash
python -m pytest cascade_rc/tests/ -q
```

Expected: all tests pass.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "test(metrics): verify CLI acceptance criterion with synthetic artefact"
```
