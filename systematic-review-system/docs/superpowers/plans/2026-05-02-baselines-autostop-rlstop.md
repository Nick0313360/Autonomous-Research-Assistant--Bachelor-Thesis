# Prompts 11.1 & 11.2: AUTOSTOP and RLStop Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vendor AUTOSTOP and RLStop stopping-method libraries and write driver scripts that produce 24-row parquets over 6 CLEF-TAR 2019 test topics × 4 target recalls, with a shared 8-column output schema concat-compatible for Phase 12 figures.

**Architecture:** Two independent drivers (`run_autostop.py`, `run_rlstop.py`) share the same output schema. AUTOSTOP runs a full CAL loop from raw text using its vendored package. RLStop trains 4 PPO models (one per target_recall) on CLEF 2017 vendor data, then applies them to test topics ranked by BM25. WSS is always computed via `cascade_rc.evaluation.metrics.wss_at_recall()`. Vendor packages live under `cascade_rc/baselines/{autostop_vendor,rlstop_vendor}/` with `VENDORED_FROM` metadata files.

**Tech Stack:** Python 3.11, scikit-learn (autostop internal), stable-baselines3 + gymnasium (rlstop), rank-bm25, pyarrow/pandas, resource (peak RSS).

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `cascade_rc/baselines/autostop_vendor/VENDORED_FROM` | **New** | Citation + license metadata |
| `cascade_rc/baselines/autostop_vendor/autostop/` | **New** | Verbatim copy of dli1/auto-stop-tar at 7e72795 |
| `cascade_rc/baselines/run_autostop.py` | **New** | AUTOSTOP driver: temp files, RET_DIR patch, CSV parse, WSS |
| `cascade_rc/baselines/rlstop_vendor/VENDORED_FROM` | **New** | Citation + license metadata |
| `cascade_rc/baselines/rlstop_vendor/rl_utils/__init__.py` | **New** | Empty — makes rl_utils a package |
| `cascade_rc/baselines/rlstop_vendor/rl_utils/rlstop_tar_env.py` | **New** | Verbatim TAREnv from ReemBinHezam/RLStop a59b622 |
| `cascade_rc/baselines/rlstop_vendor/rl_utils/ranking_utils.py` | **New** | Verbatim ranking_utils from same commit |
| `cascade_rc/baselines/rlstop_vendor/data/` | **New** | CLEF 2017 training data (42 topic rankings + qrels) |
| `cascade_rc/baselines/run_rlstop.py` | **New** | RLStop driver: BM25 rank, global inject, PPO train/infer |
| `cascade_rc/tests/test_autostop_driver.py` | **New** | Dry-run schema + mock-based functional test |
| `cascade_rc/tests/test_rlstop_driver.py` | **New** | Dry-run schema + mock SB3 inference test |
| `requirements.txt` | **Modify** | Add stable-baselines3, gymnasium |

---

## Shared Output Schema

```python
_OUTPUT_SCHEMA: dict[str, str] = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "int64",
}
```

24 rows per driver (6 topics × 4 recalls).  `pd.concat([autostop_df, rlstop_df])` → 48 rows, no NaN in `method` column.

---

## Task 1: Vendor AUTOSTOP Package

**Files:**
- Create: `cascade_rc/baselines/autostop_vendor/VENDORED_FROM`
- Create: `cascade_rc/baselines/autostop_vendor/autostop/` (all files)

- [ ] **Step 1: Clone auto-stop-tar at the pinned commit and copy into vendor directory**

```bash
git clone https://github.com/dli1/auto-stop-tar.git /tmp/autostop_clone
cd /tmp/autostop_clone && git checkout 7e72795
cp -r autostop \
    /path/to/systematic-review-system/cascade_rc/baselines/autostop_vendor/
```

Expected layout after copy:
```
cascade_rc/baselines/autostop_vendor/autostop/
├── __init__.py
├── main.py
├── tar_framework/
│   ├── __init__.py
│   ├── assessing.py
│   ├── ranking.py
│   ├── sampling_estimating.py
│   └── utils.py
└── tar_model/
    ├── __init__.py
    ├── auto_stop.py
    ├── autotar.py
    ├── knee.py
    ├── scal.py
    ├── score_distribution.py
    ├── target.py
    └── utils.py
```

- [ ] **Step 2: Write VENDORED_FROM metadata**

Create `cascade_rc/baselines/autostop_vendor/VENDORED_FROM`:

```
Source:   https://github.com/dli1/auto-stop-tar
Commit:   7e72795
License:  MIT
Vendored: 2026-05-02
Cite:     Li & Kanoulas, "When to Stop Reviewing in Technology-Assisted Reviews",
          ACM TOIS 38(4):1–36, 2020. https://doi.org/10.1145/3411755
```

- [ ] **Step 3: Verify the package imports cleanly**

```bash
cd /path/to/systematic-review-system
python3 -c "
import sys
sys.path.insert(0, 'cascade_rc/baselines/autostop_vendor')
from autostop.tar_model.auto_stop import autostop_method
import autostop.tar_framework.utils as u
print('RET_DIR:', u.RET_DIR)
print('autostop_method:', autostop_method)
"
```

Expected: prints `RET_DIR:` path and function object, no ImportError.

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/baselines/autostop_vendor/
git commit -m "feat(baselines): vendor auto-stop-tar @ 7e72795 (MIT)"
```

---

## Task 2: Write `run_autostop.py` Driver

**Files:**
- Create: `cascade_rc/baselines/run_autostop.py`

- [ ] **Step 1: Write the driver module**

Create `cascade_rc/baselines/run_autostop.py`:

```python
"""AUTOSTOP baseline driver for CASCADE-RC.

Runs the AUTOSTOP CAL loop (Li & Kanoulas 2020) on each topic parquet and
produces autostop_results.parquet with the shared 8-column schema.

RET_DIR patching: autostop.tar_framework.utils.RET_DIR is a module-level
constant. The driver replaces it with a TemporaryDirectory for each run and
restores the original in a finally block to avoid cross-run pollution.

Usage:
    python -m cascade_rc.baselines.run_autostop \\
        --data-dir data/clef_tar \\
        --out-dir  artefacts/baselines/autostop \\
        [--topics CD008874 CD012080 CD012768] \\
        [--recalls 0.80 0.90 0.95 1.0] \\
        [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import resource
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from cascade_rc.evaluation.metrics import wss_at_recall

_VENDOR = Path(__file__).parent / "autostop_vendor"
sys.path.insert(0, str(_VENDOR))

import autostop.tar_framework.utils as _as_utils  # noqa: E402
from autostop.tar_model.auto_stop import autostop_method as _autostop_method  # noqa: E402

_ORIGINAL_RET_DIR: str = _as_utils.RET_DIR

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",   # DTA
    "CD011768", "CD011975", "CD011145",   # Intervention
]
DEFAULT_RECALLS: list[float] = [0.80, 0.90, 0.95, 1.0]

_TOPIC_FAMILY: dict[str, str] = {
    "CD008874": "DTA",
    "CD012080": "DTA",
    "CD012768": "DTA",
    "CD011768": "Intervention",
    "CD011975": "Intervention",
    "CD011145": "Intervention",
}

_OUTPUT_SCHEMA: dict[str, str] = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "int64",
}


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in _OUTPUT_SCHEMA.items()})


def _get_topic_title(topic_id: str, data_dir: Path) -> str:
    """Return the systematic review title from CLEF-TAR topic file, or topic_id as fallback."""
    family = _TOPIC_FAMILY.get(topic_id, "DTA")
    topic_path = data_dir / "2019-TAR" / "Task2" / "Testing" / family / "topics" / topic_id
    if not topic_path.exists():
        return topic_id
    try:
        from cascade_rc.data.clef_tar_loader import _parse_topic_file
        title, _, _ = _parse_topic_file(topic_path)
        return title or topic_id
    except Exception:
        return topic_id


def _run_one(
    topic_id: str,
    df: pd.DataFrame,
    target_recall: float,
    data_dir: Path,
) -> dict:
    """Run AUTOSTOP for a single (topic_id, target_recall) pair."""
    title = _get_topic_title(topic_id, data_dir)
    all_pmids: list[str] = df["pmid"].tolist()
    y_true = df["y_abstract"].to_numpy(dtype=np.int64)

    with tempfile.TemporaryDirectory() as _tmpdir:
        tmpdir = Path(_tmpdir)

        # Build temp input files
        (tmpdir / "query.json").write_text(json.dumps({"title": title}))

        with (tmpdir / "qrels.txt").open("w") as f:
            for _, row in df.iterrows():
                f.write(f"{topic_id} 0 {row['pmid']} {int(row['y_abstract'])}\n")

        (tmpdir / "docids.txt").write_text("\n".join(all_pmids))

        with (tmpdir / "docs.jsonl").open("w") as f:
            for _, row in df.iterrows():
                rec = {
                    "id": row["pmid"],
                    "title": row["title"] or "",
                    "content": row["abstract"] or "",
                }
                f.write(json.dumps(rec) + "\n")

        _as_utils.RET_DIR = str(tmpdir)
        try:
            _autostop_method(
                data_name="crc",
                topic_set="test",
                topic_id=topic_id,
                query_file=str(tmpdir / "query.json"),
                qrel_file=str(tmpdir / "qrels.txt"),
                doc_id_file=str(tmpdir / "docids.txt"),
                doc_text_file=str(tmpdir / "docs.jsonl"),
                sampler_type="HTAPPriorSampler",
                stopping_recall=target_recall,
                target_recall=1.0,
                stopping_condition="loose",
                random_state=0,
            )
        finally:
            _as_utils.RET_DIR = _ORIGINAL_RET_DIR

        # Parse interaction CSV: columns are
        # t, batch_size, total_num, sampled_num, total_true_r, total_esti_r,
        # var1, var2, running_true_r, ap, running_esti_recall, running_true_recall
        csv_paths = list(tmpdir.rglob(f"{topic_id}.csv"))
        if not csv_paths:
            raise FileNotFoundError(f"No interaction CSV found for {topic_id} in {tmpdir}")
        interaction = pd.read_csv(csv_paths[0], header=None)
        examined = int(interaction.iloc[-1][3])  # sampled_num at stopping

        # Parse TREC run file: topic_id\tAF|NF\tpmid\trank\tscore\tmrun
        run_paths = list(tmpdir.rglob(f"{topic_id}.run"))
        if not run_paths:
            raise FileNotFoundError(f"No run file found for {topic_id} in {tmpdir}")
        examined_pmids = {
            line.split()[2]
            for line in run_paths[0].read_text().splitlines()
            if line.strip()
        }

    predictions = np.isin(all_pmids, list(examined_pmids)).astype(int)
    wss = wss_at_recall(predictions, y_true, target_recall=0.95)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "method":          "autostop",
        "topic_id":        topic_id,
        "target_recall":   target_recall,
        "examined":        examined,
        "recall_achieved": wss["achieved_recall"],
        "wss_95":          wss["wss"] if not (isinstance(wss["wss"], float) and np.isnan(wss["wss"])) else float("nan"),
        "wss_status":      wss["status"],
        "peak_rss_kb":     peak_rss,
    }


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    topics: list[str] = DEFAULT_TOPICS,
    recalls: list[float] = DEFAULT_RECALLS,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run AUTOSTOP sweep and write autostop_results.parquet to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df = _empty_df()
        df.to_parquet(out_dir / "autostop_results.parquet", index=False)
        logger.info("DRY-RUN: 0-row schema parquet written to %s", out_dir)
        return df

    available = [t for t in topics if (data_dir / f"{t}.parquet").exists()]
    if not available:
        raise FileNotFoundError(f"No topic parquets found in {data_dir}")
    skipped = set(topics) - set(available)
    if skipped:
        logger.warning("Skipping topics (parquet not found): %s", sorted(skipped))

    rows: list[dict] = []
    for topic_id in available:
        df_topic = pd.read_parquet(data_dir / f"{topic_id}.parquet")
        for target_recall in recalls:
            logger.info("AUTOSTOP: %s @ recall=%.2f", topic_id, target_recall)
            row = _run_one(topic_id, df_topic, target_recall, data_dir)
            rows.append(row)
            logger.info(
                "  examined=%d  wss_95=%.4f  status=%s",
                row["examined"], row["wss_95"] if not np.isnan(row["wss_95"]) else float("nan"), row["wss_status"],
            )

    df = pd.DataFrame(rows).astype(_OUTPUT_SCHEMA)
    out_path = out_dir / "autostop_results.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows to %s", len(df), out_path)
    return df


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run AUTOSTOP baseline sweep.")
    p.add_argument("--data-dir", type=Path, default=Path("data/clef_tar"),
                   help="Directory containing <topic_id>.parquet files and 2019-TAR/ tree.")
    p.add_argument("--out-dir", type=Path, default=Path("artefacts/baselines/autostop"),
                   help="Output directory for autostop_results.parquet.")
    p.add_argument("--topics", nargs="+", default=DEFAULT_TOPICS, metavar="TOPIC_ID")
    p.add_argument("--recalls", nargs="+", type=float, default=DEFAULT_RECALLS, metavar="RECALL")
    p.add_argument("--dry-run", action="store_true",
                   help="Write 0-row schema parquet without calling autostop_method.")
    return p


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _build_arg_parser().parse_args()
    run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        topics=args.topics,
        recalls=args.recalls,
        dry_run=args.dry_run,
    )
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -m py_compile cascade_rc/baselines/run_autostop.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Verify dry-run produces schema-correct parquet**

```bash
python3 -m cascade_rc.baselines.run_autostop \
    --data-dir data/clef_tar \
    --out-dir /tmp/as_dry \
    --dry-run
python3 -c "
import pandas as pd
df = pd.read_parquet('/tmp/as_dry/autostop_results.parquet')
print('rows:', len(df))
print(df.dtypes)
"
```

Expected: `rows: 0` and dtypes matching `_OUTPUT_SCHEMA`.

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/baselines/run_autostop.py
git commit -m "feat(baselines): add AUTOSTOP driver with dry-run support"
```

---

## Task 3: Test `run_autostop.py`

**Files:**
- Create: `cascade_rc/tests/test_autostop_driver.py`

- [ ] **Step 1: Write the tests**

Create `cascade_rc/tests/test_autostop_driver.py`:

```python
"""Tests for cascade_rc.baselines.run_autostop."""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

_SCHEMA = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "int64",
}

_N = 200
_PMIDS = [str(i) for i in range(_N)]
_Y = [1] * 20 + [0] * 180   # 20 relevant


def _make_topic_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "pmid":       _PMIDS,
        "title":      ["t"] * _N,
        "abstract":   ["a"] * _N,
        "y_abstract": _Y,
    }).to_parquet(path, index=False)


def _fake_autostop(data_dir: Path, topic_id: str, examined_count: int = 50) -> None:
    """Side-effect for mock: write fake CSV and run file to current RET_DIR."""
    import cascade_rc.baselines.autostop_vendor.autostop.tar_framework.utils as _as_utils

    ret_dir = Path(_as_utils.RET_DIR)
    ret_dir.mkdir(parents=True, exist_ok=True)

    # Fake interaction CSV — column 3 is sampled_num
    csv_content = f"1,10,{_N},{examined_count},20,20,0.1,0.1,0.9,0.3,0.95,0.9\n"
    csv_dir = ret_dir / "crc" / "interaction" / "fake" / "test" / "0"
    csv_dir.mkdir(parents=True, exist_ok=True)
    (csv_dir / f"{topic_id}.csv").write_text(csv_content)

    # Fake TREC run file — first `examined_count` PMIDs marked AF
    run_dir = ret_dir / "crc" / "tar_run" / "fake" / "test" / "0"
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"{topic_id}\tAF\t{pmid}\t{i+1}\t{-i}\tmrun"
             for i, pmid in enumerate(_PMIDS[:examined_count])]
    (run_dir / f"{topic_id}.run").write_text("\n".join(lines))


def test_dry_run_zero_rows_correct_schema(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_autostop import run_sweep

    df = run_sweep(
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        dry_run=True,
    )
    assert len(df) == 0
    for col, dtype in _SCHEMA.items():
        assert col in df.columns, f"Missing column: {col}"
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"


def test_dry_run_parquet_written(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_autostop import run_sweep

    out_dir = tmp_path / "out"
    run_sweep(data_dir=tmp_path / "data", out_dir=out_dir, dry_run=True)
    assert (out_dir / "autostop_results.parquet").exists()


def test_no_parquets_raises(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_autostop import run_sweep

    with pytest.raises(FileNotFoundError):
        run_sweep(data_dir=tmp_path / "empty", out_dir=tmp_path / "out")


def test_single_topic_single_recall_mock(tmp_path: Path) -> None:
    """Functional test: mocked autostop_method writes expected files; driver parses them."""
    from cascade_rc.baselines.run_autostop import run_sweep

    data_dir = tmp_path / "data"
    _make_topic_parquet(data_dir / "CD008874.parquet")

    def _side_effect(*args, **kwargs) -> None:
        _fake_autostop(data_dir, "CD008874", examined_count=50)

    with mock.patch("cascade_rc.baselines.run_autostop._autostop_method",
                    side_effect=_side_effect):
        df = run_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "out",
            topics=["CD008874"],
            recalls=[0.95],
        )

    assert len(df) == 1
    row = df.iloc[0]
    assert row["method"] == "autostop"
    assert row["topic_id"] == "CD008874"
    assert float(row["target_recall"]) == pytest.approx(0.95)
    assert int(row["examined"]) == 50
    assert row["wss_status"] in {"ok", "recall_target_missed", "no_relevant_docs"}
    assert int(row["peak_rss_kb"]) > 0


def test_output_schema_dtypes_after_real_run(tmp_path: Path) -> None:
    """Verify astype(_OUTPUT_SCHEMA) produces correct column dtypes after mock run."""
    from cascade_rc.baselines.run_autostop import run_sweep

    data_dir = tmp_path / "data"
    _make_topic_parquet(data_dir / "CD008874.parquet")

    def _side_effect(*args, **kwargs) -> None:
        _fake_autostop(data_dir, "CD008874", examined_count=50)

    with mock.patch("cascade_rc.baselines.run_autostop._autostop_method",
                    side_effect=_side_effect):
        df = run_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "out",
            topics=["CD008874"],
            recalls=[0.95],
        )

    for col, dtype in _SCHEMA.items():
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest cascade_rc/tests/test_autostop_driver.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add cascade_rc/tests/test_autostop_driver.py
git commit -m "test(baselines): add AUTOSTOP driver tests (dry-run + mock functional)"
```

---

## Task 4: Vendor RLStop Package

**Files:**
- Create: `cascade_rc/baselines/rlstop_vendor/VENDORED_FROM`
- Create: `cascade_rc/baselines/rlstop_vendor/rl_utils/__init__.py`
- Create: `cascade_rc/baselines/rlstop_vendor/rl_utils/rlstop_tar_env.py`
- Create: `cascade_rc/baselines/rlstop_vendor/rl_utils/ranking_utils.py`
- Create: `cascade_rc/baselines/rlstop_vendor/data/` (training corpus)

- [ ] **Step 1: Clone RLStop at the pinned commit and copy rl_utils**

```bash
git clone https://github.com/ReemBinHezam/RLStop.git /tmp/rlstop_clone
cd /tmp/rlstop_clone && git checkout a59b622
mkdir -p cascade_rc/baselines/rlstop_vendor/rl_utils
cp rl_utils/rlstop_tar_env.py \
   rl_utils/ranking_utils.py \
   cascade_rc/baselines/rlstop_vendor/rl_utils/
touch cascade_rc/baselines/rlstop_vendor/rl_utils/__init__.py
```

Expected files after copy:
```
cascade_rc/baselines/rlstop_vendor/rl_utils/
├── __init__.py           (empty)
├── rlstop_tar_env.py     (verbatim)
└── ranking_utils.py      (verbatim)
```

- [ ] **Step 2: Copy CLEF 2017 training data**

The training corpus uses two data sources from the vendor repo:
- `data/clef2017/docids/` — 42 per-topic files, each containing PMIDs in rank order (one per line)
- `data/qrels/CLEF2017_qrels.txt` — TREC qrel file

```bash
mkdir -p cascade_rc/baselines/rlstop_vendor/data/clef2017
mkdir -p cascade_rc/baselines/rlstop_vendor/data/qrels
cp -r data/clef2017/docids cascade_rc/baselines/rlstop_vendor/data/clef2017/
cp data/qrels/CLEF2017_qrels.txt cascade_rc/baselines/rlstop_vendor/data/qrels/
```

- [ ] **Step 3: Write VENDORED_FROM metadata**

Create `cascade_rc/baselines/rlstop_vendor/VENDORED_FROM`:

```
Source:   https://github.com/ReemBinHezam/RLStop
Commit:   a59b622
License:  Apache-2.0
Vendored: 2026-05-02
Cite:     Bin-Hezam & Stevenson, "RLStop: A Reinforcement Learning Stopping Method for TAR",
          SIGIR 2024. https://doi.org/10.1145/3626772.3657837

Deviations from paper:
  - Training data: CLEF 2017 only (42 Intervention topics, vendor-provided rankings).
    CLEF 2018 not shipped with the vendor repo; per-family training protocol (paper §4)
    cannot be replicated without CLEF 2018 family labels.
  - One model per target_recall (4 total) trained cross-family and applied to all
    6 CLEF-TAR 2019 test topics. Paper trains per-family; not reproducible here.
  - n_steps=100 per vendor notebook (paper §4 states batch=100; vendor confirms).
```

- [ ] **Step 4: Verify vendor layout**

```bash
ls cascade_rc/baselines/rlstop_vendor/rl_utils/
ls cascade_rc/baselines/rlstop_vendor/data/clef2017/docids/ | wc -l  # expect 42
wc -l cascade_rc/baselines/rlstop_vendor/data/qrels/CLEF2017_qrels.txt  # expect ~241670
```

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/baselines/rlstop_vendor/
git commit -m "feat(baselines): vendor RLStop @ a59b622 (Apache-2.0) + CLEF2017 training data"
```

---

## Task 5: Add RLStop Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add stable-baselines3 and gymnasium to requirements.txt**

Append to `requirements.txt`:

```
stable-baselines3>=2.0.0
gymnasium>=0.29.0
```

- [ ] **Step 2: Install in the project venv**

```bash
pip install "stable-baselines3>=2.0.0" "gymnasium>=0.29.0"
```

- [ ] **Step 3: Verify**

```bash
python3 -c "from stable_baselines3 import PPO; from gymnasium import spaces; print('SB3 OK')"
```

Expected: `SB3 OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add stable-baselines3 and gymnasium for RLStop baseline"
```

---

## Task 6: Write `run_rlstop.py` Driver

**Files:**
- Create: `cascade_rc/baselines/run_rlstop.py`

The driver injects 8 module-level globals into `rlstop_tar_env.py` before every `TAREnv` instantiation. `n_jobs=1` is enforced because these global injections are not thread-safe. The `make_windows` and `get_rel_cnt_rate` functions (referenced as globals inside `TAREnv`) are also injected from the driver.

- [ ] **Step 1: Write the driver module**

Create `cascade_rc/baselines/run_rlstop.py`:

```python
"""RLStop baseline driver for CASCADE-RC.

Trains one PPO model per target_recall (4 models) on CLEF 2017 vendor data,
then applies each model to CLEF-TAR 2019 test topics ranked by BM25.

THREAD SAFETY NOTE: TAREnv reads 8 module-level globals from rlstop_tar_env.
Global mutation is not thread-safe. n_jobs=1 is enforced throughout — the
24-inference run takes minutes serially and parallelism is unnecessary.

Usage:
    python -m cascade_rc.baselines.run_rlstop \\
        --data-dir  data/clef_tar \\
        --out-dir   artefacts/baselines/rlstop \\
        --train-dir artefacts/baselines/rlstop \\
        [--topics CD008874 ...] \\
        [--recalls 0.80 0.90 0.95 1.0] \\
        [--skip-train] \\
        [--force-retrain] \\
        [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import random
import resource
from pathlib import Path

import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi

from cascade_rc.evaluation.metrics import wss_at_recall

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]
DEFAULT_RECALLS: list[float] = [0.80, 0.90, 0.95, 1.0]

_TOPIC_FAMILY: dict[str, str] = {
    "CD008874": "DTA",
    "CD012080": "DTA",
    "CD012768": "DTA",
    "CD011768": "Intervention",
    "CD011975": "Intervention",
    "CD011145": "Intervention",
}

_VECTOR_SIZE = 100  # TAREnv observation dimension

_OUTPUT_SCHEMA: dict[str, str] = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "int64",
}

_VENDOR = Path(__file__).parent / "rlstop_vendor"


# ---------------------------------------------------------------------------
# make_windows — referenced as a global in TAREnv; not defined in vendor code
# ---------------------------------------------------------------------------

def _make_windows(vector_size: int, n_docs: int) -> list[tuple[int, int]]:
    """Divide n_docs into vector_size equal windows of (start, end) index pairs."""
    window_size = max(1, n_docs // vector_size)
    return [(i * window_size, (i + 1) * window_size) for i in range(vector_size)]


# ---------------------------------------------------------------------------
# Training data helpers
# ---------------------------------------------------------------------------

def _load_training_qrels(vendor_dir: Path) -> dict[str, dict[str, int]]:
    """Parse CLEF2017_qrels.txt into {topic_id: {pmid: 0|1}}."""
    qrels_path = vendor_dir / "data" / "qrels" / "CLEF2017_qrels.txt"
    qrels: dict[str, dict[str, int]] = {}
    for line in qrels_path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        topic, pmid, rel = parts[0], parts[2], int(parts[3])
        qrels.setdefault(topic, {})[pmid] = rel
    return qrels


def _build_training_dicts(
    vendor_dir: Path,
) -> tuple[dict[str, list[str]], dict[str, list[int]]]:
    """Build doc_rank_dic and rank_rel_dic from CLEF 2017 vendor data.

    doc_rank_dic:  {topic_id: [pmid, ...]}  — PMIDs in pre-ranked order
    rank_rel_dic:  {topic_id: [0|1, ...]}   — relevance label in rank order
    """
    docids_dir = vendor_dir / "data" / "clef2017" / "docids"
    qrels = _load_training_qrels(vendor_dir)

    doc_rank_dic: dict[str, list[str]] = {}
    rank_rel_dic: dict[str, list[int]] = {}

    for docid_file in sorted(docids_dir.iterdir()):
        topic_id = docid_file.name
        pmids = [p.strip() for p in docid_file.read_text().splitlines() if p.strip()]
        if len(pmids) < _VECTOR_SIZE:
            logger.warning(
                "Skipping training topic %s: %d docs < vector_size=%d",
                topic_id, len(pmids), _VECTOR_SIZE,
            )
            continue
        doc_rank_dic[topic_id] = pmids
        topic_q = qrels.get(topic_id, {})
        rank_rel_dic[topic_id] = [topic_q.get(pmid, 0) for pmid in pmids]

    return doc_rank_dic, rank_rel_dic


# ---------------------------------------------------------------------------
# BM25 ranking for test topics
# ---------------------------------------------------------------------------

def _get_topic_title(topic_id: str, data_dir: Path) -> str:
    family = _TOPIC_FAMILY.get(topic_id, "DTA")
    topic_path = data_dir / "2019-TAR" / "Task2" / "Testing" / family / "topics" / topic_id
    if not topic_path.exists():
        return topic_id
    try:
        from cascade_rc.data.clef_tar_loader import _parse_topic_file
        title, _, _ = _parse_topic_file(topic_path)
        return title or topic_id
    except Exception:
        return topic_id


def _bm25_rank(df: pd.DataFrame, query: str) -> list[str]:
    """Return PMIDs sorted by BM25 score descending using query."""
    corpus = [
        (str(r.title or "") + " " + str(r.abstract or "")).lower().split()
        for r in df.itertuples()
    ]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query.lower().split())
    ranked_idx = np.argsort(-scores)
    return df["pmid"].iloc[ranked_idx].tolist()


# ---------------------------------------------------------------------------
# Global injection into TAREnv
# ---------------------------------------------------------------------------

def _inject_globals(
    topic_id: str,
    doc_rank_dic: dict[str, list[str]],
    rank_rel_dic: dict[str, list[int]],
) -> None:
    """Inject all module-level globals required by TAREnv before instantiation."""
    import cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env as _env_mod
    import cascade_rc.baselines.rlstop_vendor.rl_utils.ranking_utils as _rank_mod

    _env_mod.doc_rank_dic = doc_rank_dic
    _env_mod.rank_rel_dic = rank_rel_dic
    _env_mod.SELECTED_TOPICS = []
    _env_mod.TRAINING = True
    _env_mod.SELECTED_TOPICS_ORDERERD = [topic_id]
    _env_mod.SELECTED_TOPICS_ORDERERD_INDEX = 0
    _env_mod.make_windows = _make_windows
    _env_mod.get_rel_cnt_rate = _rank_mod.get_rel_cnt_rate
    _env_mod.random = random

    _rank_mod.doc_rank_dic = doc_rank_dic
    _rank_mod.rank_rel_dic = rank_rel_dic
    _rank_mod.make_windows = _make_windows


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def _linear_schedule(initial_value: float):
    def func(progress_remaining: float) -> float:
        return progress_remaining * initial_value
    return func


def _train_model(
    target_recall: float,
    train_doc_rank_dic: dict[str, list[str]],
    train_rank_rel_dic: dict[str, list[int]],
    cache_path: Path,
    force_retrain: bool = False,
) -> "PPO":  # type: ignore[name-defined]
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_util import DummyVecEnv
    from cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env import TAREnv

    if cache_path.exists() and not force_retrain:
        logger.info("Loading cached model: %s", cache_path)
        return PPO.load(str(cache_path))

    train_topics = sorted(train_doc_rank_dic.keys())

    def _make_env(t_id: str):
        def _fn():
            _inject_globals(t_id, train_doc_rank_dic, train_rank_rel_dic)
            return TAREnv(target_recall=target_recall, topic_id=t_id, size=_VECTOR_SIZE)
        return _fn

    import cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env as _env_mod
    _env_mod.TRAINING = True
    _env_mod.SELECTED_TOPICS_ORDERERD = train_topics
    _env_mod.SELECTED_TOPICS_ORDERERD_INDEX = 0

    from stable_baselines3.common.env_util import DummyVecEnv
    vec_env = DummyVecEnv([_make_env(t) for t in train_topics])

    model = PPO(
        policy="MlpPolicy",
        env=vec_env,
        n_steps=100,
        batch_size=100,
        n_epochs=8,
        gamma=0.99,
        gae_lambda=0.98,
        ent_coef=0.01,
        clip_range=0.2,
        learning_rate=_linear_schedule(1e-4),
        seed=0,
        verbose=0,
    )
    logger.info("Training PPO for target_recall=%.2f (%d topics) ...", target_recall, len(train_topics))
    model.learn(total_timesteps=100_000)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(cache_path))
    logger.info("Model saved: %s", cache_path)
    return model


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _infer_one(
    topic_id: str,
    df: pd.DataFrame,
    target_recall: float,
    model: "PPO",  # type: ignore[name-defined]
    data_dir: Path,
) -> dict:
    from cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env import TAREnv

    query = _get_topic_title(topic_id, data_dir)
    ranked_pmids = _bm25_rank(df, query)
    all_pmids = df["pmid"].tolist()
    y_true = df["y_abstract"].to_numpy(dtype=np.int64)

    infer_doc_rank = {topic_id: ranked_pmids}
    infer_rank_rel = {
        topic_id: [
            int(df[df["pmid"] == pmid]["y_abstract"].iloc[0])
            for pmid in ranked_pmids
        ]
    }

    _inject_globals(topic_id, infer_doc_rank, infer_rank_rel)
    env = TAREnv(target_recall=target_recall, topic_id=topic_id, size=_VECTOR_SIZE)
    obs, _ = env.reset()

    done = False
    for _ in range(_VECTOR_SIZE + 1):
        action, _ = model.predict(obs, deterministic=True)
        obs, _, terminated, truncated, _ = env.step(int(action))
        done = terminated or truncated
        if done:
            break

    examined = int(env.n_samp_docs)
    examined_pmids = set(ranked_pmids[:examined])

    predictions = np.isin(all_pmids, list(examined_pmids)).astype(int)
    wss = wss_at_recall(predictions, y_true, target_recall=0.95)
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "method":          "rlstop",
        "topic_id":        topic_id,
        "target_recall":   target_recall,
        "examined":        examined,
        "recall_achieved": wss["achieved_recall"],
        "wss_95":          wss["wss"],
        "wss_status":      wss["status"],
        "peak_rss_kb":     peak_rss,
    }


# ---------------------------------------------------------------------------
# Public sweep entry point
# ---------------------------------------------------------------------------

def _empty_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=dt) for col, dt in _OUTPUT_SCHEMA.items()})


def run_sweep(
    data_dir: Path,
    out_dir: Path,
    train_dir: Path,
    topics: list[str] = DEFAULT_TOPICS,
    recalls: list[float] = DEFAULT_RECALLS,
    skip_train: bool = False,
    force_retrain: bool = False,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run RLStop sweep and write rlstop_results.parquet to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    train_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        df = _empty_df()
        df.to_parquet(out_dir / "rlstop_results.parquet", index=False)
        logger.info("DRY-RUN: 0-row schema parquet written to %s", out_dir)
        return df

    available = [t for t in topics if (data_dir / f"{t}.parquet").exists()]
    if not available:
        raise FileNotFoundError(f"No topic parquets found in {data_dir}")
    skipped = set(topics) - set(available)
    if skipped:
        logger.warning("Skipping topics (parquet not found): %s", sorted(skipped))

    train_doc_rank_dic, train_rank_rel_dic = _build_training_dicts(_VENDOR)

    # Write artefacts README on first run
    readme_path = out_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# RLStop Model Weights\n\n"
            "Naming:     `recall_<target_recall>.zip`  (SB3 PPO format)\n"
            "Trained on: CLEF 2017 (42 Intervention topics, vendor-provided rankings)\n"
            "PPO steps:  100 000\n"
            "Hyperparams: n_steps=100 batch_size=100 n_epochs=8 gamma=0.99 gae_lambda=0.98\n"
            "             ent_coef=0.01 clip_range=0.2 lr=linear_schedule(1e-4) seed=0\n"
            "Applied to: all available CLEF-TAR 2019 test topics (cross-family — see VENDORED_FROM)\n"
        )

    rows: list[dict] = []
    for target_recall in recalls:
        cache_path = train_dir / f"recall_{target_recall:.2f}.zip"
        if not skip_train:
            model = _train_model(
                target_recall, train_doc_rank_dic, train_rank_rel_dic,
                cache_path, force_retrain=force_retrain,
            )
        else:
            from stable_baselines3 import PPO
            if not cache_path.exists():
                raise FileNotFoundError(
                    f"--skip-train requested but model not found: {cache_path}"
                )
            model = PPO.load(str(cache_path))

        for topic_id in available:
            df_topic = pd.read_parquet(data_dir / f"{topic_id}.parquet")
            logger.info("RLStop infer: %s @ recall=%.2f", topic_id, target_recall)
            row = _infer_one(topic_id, df_topic, target_recall, model, data_dir)
            rows.append(row)
            logger.info(
                "  examined=%d  wss_status=%s", row["examined"], row["wss_status"]
            )

    df = pd.DataFrame(rows).astype(_OUTPUT_SCHEMA)
    out_path = out_dir / "rlstop_results.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("Wrote %d rows to %s", len(df), out_path)
    return df


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run RLStop baseline sweep.")
    p.add_argument("--data-dir", type=Path, default=Path("data/clef_tar"))
    p.add_argument("--out-dir", type=Path, default=Path("artefacts/baselines/rlstop"))
    p.add_argument("--train-dir", type=Path, default=Path("artefacts/baselines/rlstop"),
                   help="Directory where model .zip files are cached.")
    p.add_argument("--topics", nargs="+", default=DEFAULT_TOPICS, metavar="TOPIC_ID")
    p.add_argument("--recalls", nargs="+", type=float, default=DEFAULT_RECALLS, metavar="RECALL")
    p.add_argument("--skip-train", action="store_true",
                   help="Load cached .zip models; fail if not present.")
    p.add_argument("--force-retrain", action="store_true",
                   help="Ignore cached .zip files and retrain from scratch.")
    p.add_argument("--dry-run", action="store_true",
                   help="Write 0-row schema parquet without training or inference.")
    return p


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    args = _build_arg_parser().parse_args()
    run_sweep(
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        train_dir=args.train_dir,
        topics=args.topics,
        recalls=args.recalls,
        skip_train=args.skip_train,
        force_retrain=args.force_retrain,
        dry_run=args.dry_run,
    )
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -m py_compile cascade_rc/baselines/run_rlstop.py && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Verify dry-run**

```bash
python3 -m cascade_rc.baselines.run_rlstop \
    --data-dir data/clef_tar \
    --out-dir /tmp/rl_dry \
    --train-dir /tmp/rl_dry \
    --dry-run
python3 -c "
import pandas as pd
df = pd.read_parquet('/tmp/rl_dry/rlstop_results.parquet')
print('rows:', len(df)); print(df.dtypes)
"
```

Expected: `rows: 0` and dtypes matching `_OUTPUT_SCHEMA`.

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/baselines/run_rlstop.py
git commit -m "feat(baselines): add RLStop driver with BM25 ranking, PPO train/infer, dry-run"
```

---

## Task 7: Test `run_rlstop.py`

**Files:**
- Create: `cascade_rc/tests/test_rlstop_driver.py`

- [ ] **Step 1: Write the tests**

Create `cascade_rc/tests/test_rlstop_driver.py`:

```python
"""Tests for cascade_rc.baselines.run_rlstop."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
import pytest

_SCHEMA = {
    "method":          "object",
    "topic_id":        "object",
    "target_recall":   "float64",
    "examined":        "int64",
    "recall_achieved": "float64",
    "wss_95":          "float64",
    "wss_status":      "object",
    "peak_rss_kb":     "int64",
}

_N = 200
_PMIDS = [str(i) for i in range(_N)]
_Y = [1] * 20 + [0] * 180


def _make_topic_parquet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "pmid":       _PMIDS,
        "title":      ["A B C"] * _N,
        "abstract":   ["D E F"] * _N,
        "y_abstract": _Y,
    }).to_parquet(path, index=False)


def test_dry_run_zero_rows_correct_schema(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_rlstop import run_sweep

    df = run_sweep(
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        train_dir=tmp_path / "train",
        dry_run=True,
    )
    assert len(df) == 0
    for col, dtype in _SCHEMA.items():
        assert col in df.columns, f"Missing column: {col}"
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"


def test_dry_run_parquet_written(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_rlstop import run_sweep

    out_dir = tmp_path / "out"
    run_sweep(
        data_dir=tmp_path / "data",
        out_dir=out_dir,
        train_dir=tmp_path / "train",
        dry_run=True,
    )
    assert (out_dir / "rlstop_results.parquet").exists()


def test_no_parquets_raises(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_rlstop import run_sweep

    with pytest.raises(FileNotFoundError):
        run_sweep(
            data_dir=tmp_path / "empty",
            out_dir=tmp_path / "out",
            train_dir=tmp_path / "train",
        )


def test_infer_one_with_mock_model(tmp_path: Path) -> None:
    """Mock model.predict to return STOP(1) on first step; verify examined count."""
    from cascade_rc.baselines.run_rlstop import (
        _infer_one, _inject_globals, _make_windows, _build_training_dicts,
    )
    from cascade_rc.baselines.rlstop_vendor.rl_utils.rlstop_tar_env import TAREnv
    import cascade_rc.baselines.rlstop_vendor.rl_utils.ranking_utils as _rank_mod

    data_dir = tmp_path / "data"
    df_topic = pd.DataFrame({
        "pmid":       _PMIDS,
        "title":      ["term"] * _N,
        "abstract":   ["word"] * _N,
        "y_abstract": _Y,
    })

    ranked = _PMIDS[:]
    infer_doc = {"CD008874": ranked}
    infer_rel = {"CD008874": _Y}

    _inject_globals("CD008874", infer_doc, infer_rel)

    # Model always predicts STOP (action=1) immediately
    mock_model = mock.MagicMock()
    mock_model.predict.return_value = (np.array(1), None)

    _make_topic_parquet(data_dir / "CD008874.parquet")
    row = _infer_one("CD008874", df_topic, 0.95, mock_model, data_dir)

    assert row["method"] == "rlstop"
    assert row["topic_id"] == "CD008874"
    assert float(row["target_recall"]) == pytest.approx(0.95)
    assert row["wss_status"] in {"ok", "recall_target_missed", "no_relevant_docs"}
    assert int(row["peak_rss_kb"]) > 0


def test_make_windows_basic() -> None:
    from cascade_rc.baselines.run_rlstop import _make_windows

    windows = _make_windows(vector_size=100, n_docs=200)
    assert len(windows) == 100
    # window_size = 200 // 100 = 2
    assert windows[0] == (0, 2)
    assert windows[99] == (198, 200)


def test_make_windows_small_docs() -> None:
    from cascade_rc.baselines.run_rlstop import _make_windows

    # 119 docs → window_size = 1
    windows = _make_windows(vector_size=100, n_docs=119)
    assert len(windows) == 100
    assert windows[0] == (0, 1)


def test_output_schema_dtypes_after_mock_infer(tmp_path: Path) -> None:
    from cascade_rc.baselines.run_rlstop import run_sweep

    data_dir = tmp_path / "data"
    _make_topic_parquet(data_dir / "CD008874.parquet")

    mock_model = mock.MagicMock()
    mock_model.predict.return_value = (np.array(1), None)

    with (
        mock.patch("cascade_rc.baselines.run_rlstop._train_model", return_value=mock_model),
        mock.patch("cascade_rc.baselines.run_rlstop._build_training_dicts", return_value=({}, {})),
    ):
        df = run_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "out",
            train_dir=tmp_path / "train",
            topics=["CD008874"],
            recalls=[0.95],
        )

    assert len(df) == 1
    for col, dtype in _SCHEMA.items():
        assert str(df[col].dtype) == dtype, f"{col}: expected {dtype}, got {df[col].dtype}"
```

- [ ] **Step 2: Run tests**

```bash
python3 -m pytest cascade_rc/tests/test_rlstop_driver.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add cascade_rc/tests/test_rlstop_driver.py
git commit -m "test(baselines): add RLStop driver tests (dry-run + mock inference)"
```

---

## Task 8: Integration Schema-Parity Test

**Files:**
- Modify: `cascade_rc/tests/test_autostop_driver.py` (add concat test at the bottom)

- [ ] **Step 1: Add schema-parity test**

Append to `cascade_rc/tests/test_autostop_driver.py`:

```python
def test_schema_parity_concat(tmp_path: Path) -> None:
    """pd.concat of autostop_df and rlstop_df must yield 48 rows, no NaN method column."""
    from cascade_rc.baselines.run_autostop import run_sweep as as_sweep, _OUTPUT_SCHEMA as as_schema
    from cascade_rc.baselines.run_rlstop import run_sweep as rl_sweep

    data_dir = tmp_path / "data"
    _make_topic_parquet(data_dir / "CD008874.parquet")

    def _as_side_effect(*args, **kwargs) -> None:
        _fake_autostop(data_dir, "CD008874", examined_count=50)

    mock_model = mock.MagicMock()
    mock_model.predict.return_value = (np.array(1), None)

    with mock.patch("cascade_rc.baselines.run_autostop._autostop_method",
                    side_effect=_as_side_effect):
        df_as = as_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "as_out",
            topics=["CD008874"],
            recalls=[0.80, 0.90, 0.95, 1.0],
        )

    with (
        mock.patch("cascade_rc.baselines.run_rlstop._train_model", return_value=mock_model),
        mock.patch("cascade_rc.baselines.run_rlstop._build_training_dicts", return_value=({}, {})),
    ):
        df_rl = rl_sweep(
            data_dir=data_dir,
            out_dir=tmp_path / "rl_out",
            train_dir=tmp_path / "train",
            topics=["CD008874"],
            recalls=[0.80, 0.90, 0.95, 1.0],
        )

    combined = pd.concat([df_as, df_rl], ignore_index=True)

    assert len(combined) == 8   # 1 topic × 4 recalls × 2 methods
    assert combined["method"].notna().all()
    assert set(combined["method"].unique()) == {"autostop", "rlstop"}
    assert combined.columns.tolist() == list(as_schema.keys())
```

- [ ] **Step 2: Run all baseline tests together**

```bash
python3 -m pytest cascade_rc/tests/test_autostop_driver.py \
                   cascade_rc/tests/test_rlstop_driver.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 3: Commit**

```bash
git add cascade_rc/tests/test_autostop_driver.py
git commit -m "test(baselines): add schema-parity concat test for autostop + rlstop"
```

---

## Notes for Full 24-Row Run (all 6 topics)

The 3 Intervention parquets (CD011768, CD011975, CD011145) are not pre-generated. To produce 24-row results:

```bash
# Generate Intervention parquets (requires PubMed network access)
python3 -m cascade_rc.data.clef_tar_loader \
    --topics CD011768 CD011975 CD011145 \
    --out data/clef_tar \
    --data-dir data/clef_tar

# Run AUTOSTOP on all 6 topics
python3 -m cascade_rc.baselines.run_autostop \
    --data-dir data/clef_tar \
    --out-dir  artefacts/baselines/autostop

# Train + run RLStop (first run trains 4 PPO models ~20 min)
python3 -m cascade_rc.baselines.run_rlstop \
    --data-dir  data/clef_tar \
    --out-dir   artefacts/baselines/rlstop \
    --train-dir artefacts/baselines/rlstop

# Re-use cached models
python3 -m cascade_rc.baselines.run_rlstop \
    --data-dir  data/clef_tar \
    --out-dir   artefacts/baselines/rlstop \
    --train-dir artefacts/baselines/rlstop \
    --skip-train
```
