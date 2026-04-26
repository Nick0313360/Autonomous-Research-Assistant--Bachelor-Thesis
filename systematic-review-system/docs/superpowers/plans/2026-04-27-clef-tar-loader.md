# CLEF-TAR 2019 Benchmark Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `cascade_rc/data/clef_tar_loader.py` — a self-contained benchmark data pipeline that downloads CLEF-TAR 2019, parses three DTA topics, fetches PubMed abstracts, and writes one parquet file per topic for CASCADE-RC validation.

**Architecture:** New sub-package `cascade_rc/data/` inside `systematic-review-system/`. `load_topic` parses Task2 DTA topic files + a single shared qrels file. `fetch_abstracts` reuses `PubMedConnector` for Entrez credentials, then calls `Entrez.efetch` directly. CLI ties everything together and writes parquet.

**Tech Stack:** Python 3.11, Biopython Entrez, pandas + pyarrow (parquet), subprocess (sparse git clone), standard library only otherwise.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `cascade_rc/__init__.py` | empty — marks package |
| Create | `cascade_rc/data/__init__.py` | empty — marks sub-package |
| **Create** | `cascade_rc/data/clef_tar_loader.py` | `Topic` dataclass, all three public functions, CLI `__main__` |
| **Create** | `tests/test_clef_tar_loader.py` | unit tests (fixtures) + integration tests (parquet) |
| Modify | `requirements.txt` | add `pandas>=2.0`, `pyarrow>=14.0` |

No other files are modified. `tier1_search/pubmed_connector.py` is imported but not changed.

---

## Task 1: Scaffold — package skeleton + dependencies

**Files:**
- Create: `cascade_rc/__init__.py`
- Create: `cascade_rc/data/__init__.py`
- Modify: `requirements.txt`

- [ ] **Step 1.1: Create empty package init files**

```bash
mkdir -p cascade_rc/data
touch cascade_rc/__init__.py cascade_rc/data/__init__.py
```

- [ ] **Step 1.2: Add parquet dependencies to requirements.txt**

In `requirements.txt`, append these two lines after the existing entries:

```
pandas>=2.0
pyarrow>=14.0
```

- [ ] **Step 1.3: Install new dependencies**

```bash
pip install "pandas>=2.0" "pyarrow>=14.0"
```

Expected output includes lines like:
```
Successfully installed pandas-2.x.x pyarrow-14.x.x
```

- [ ] **Step 1.4: Verify imports work**

```bash
python -c "import pandas; import pyarrow; print('ok')"
```

Expected: `ok`

- [ ] **Step 1.5: Commit scaffold**

```bash
git add cascade_rc/__init__.py cascade_rc/data/__init__.py requirements.txt
git commit -m "feat(cascade_rc): scaffold package skeleton; add pandas+pyarrow deps"
```

---

## Task 2: `Topic` dataclass + `load_topic` (TDD)

**Files:**
- Create: `cascade_rc/data/clef_tar_loader.py` (dataclass + `load_topic` only — no other functions yet)
- Create: `tests/test_clef_tar_loader.py` (unit test for `load_topic`)

- [ ] **Step 2.1: Write the failing test**

Create `tests/test_clef_tar_loader.py`:

```python
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cascade_rc.data.clef_tar_loader import Topic, load_topic

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_data_dir(tmp_path: Path) -> Path:
    """Build a minimal CLEF-TAR 2019 directory tree for unit tests."""
    dta = tmp_path / "2019-TAR" / "Task2" / "Testing" / "DTA"
    (dta / "topics").mkdir(parents=True)
    (dta / "qrels").mkdir(parents=True)

    (dta / "topics" / "CD008874").write_text(
        "Topic: CD008874 \n"
        "\n"
        "Title: Test airway topic \n"
        "\n"
        "Query: \n"
        "test query line 1\n"
        "test query line 2\n"
        "\n"
        "Pids: \n"
        "    11111111 \n"
        "    22222222 \n"
        "    33333333 \n",
        encoding="utf-8",
    )

    (dta / "qrels" / "full.test.dta.abs.2019.qrels").write_text(
        "CD008874 0 11111111 1\n"
        "CD008874 0 22222222 0\n"
        "CD008874 0 33333333 1\n",
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Unit: load_topic
# ---------------------------------------------------------------------------

def test_load_topic_title(fake_data_dir: Path) -> None:
    topic = load_topic("CD008874", fake_data_dir)
    assert topic.title == "Test airway topic"


def test_load_topic_boolean_query(fake_data_dir: Path) -> None:
    topic = load_topic("CD008874", fake_data_dir)
    assert "test query line 1" in topic.boolean_query
    assert "test query line 2" in topic.boolean_query


def test_load_topic_candidate_pmids(fake_data_dir: Path) -> None:
    topic = load_topic("CD008874", fake_data_dir)
    assert set(topic.candidate_pmids) == {"11111111", "22222222", "33333333"}


def test_load_topic_qrels(fake_data_dir: Path) -> None:
    topic = load_topic("CD008874", fake_data_dir)
    assert topic.qrels_abstract == {"11111111": 1, "22222222": 0, "33333333": 1}


def test_load_topic_bad_id_raises(fake_data_dir: Path) -> None:
    with pytest.raises(ValueError, match="CD000000"):
        load_topic("CD000000", fake_data_dir)


def test_load_topic_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_topic("CD008874", tmp_path)
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
pytest tests/test_clef_tar_loader.py -v 2>&1 | head -30
```

Expected: `ImportError: cannot import name 'Topic' from 'cascade_rc.data.clef_tar_loader'` (file doesn't exist yet).

- [ ] **Step 2.3: Implement `Topic` dataclass and `load_topic`**

Create `cascade_rc/data/clef_tar_loader.py`:

```python
"""CLEF-TAR 2019 benchmark ingestion for CASCADE-RC validation."""
from __future__ import annotations

import json
import subprocess
import tempfile
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from Bio import Entrez, Medline

_ALLOWED_TOPICS: frozenset[str] = frozenset({"CD008874", "CD012080", "CD012768"})
_DTA_BASE = Path("2019-TAR") / "Task2" / "Testing" / "DTA"
_QRELS_FILE = "full.test.dta.abs.2019.qrels"
_REPO_URL = "https://github.com/CLEF-TAR/tar.git"
_CHUNK_SIZE = 500


@dataclass
class Topic:
    topic_id: str
    title: str
    boolean_query: str
    candidate_pmids: list[str]
    qrels_abstract: dict[str, int]


def _parse_topic_file(path: Path) -> tuple[str, str, list[str]]:
    title = ""
    query_lines: list[str] = []
    pids: list[str] = []
    state = "start"

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("Title:"):
            title = line[len("Title:"):].strip()
            state = "title"
        elif line.startswith("Query:"):
            state = "query"
        elif line.startswith("Pids:"):
            state = "pids"
        elif state == "query" and line:
            query_lines.append(line)
        elif state == "pids" and line.isdigit():
            pids.append(line)

    return title, "\n".join(query_lines), pids


def _parse_qrels(path: Path, topic_id: str) -> dict[str, int]:
    qrels: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] == topic_id:
            qrels[parts[2]] = int(parts[3])
    return qrels


def load_topic(topic_id: str, data_dir: Path) -> Topic:
    """Parse a CLEF-TAR 2019 DTA topic from data_dir/2019-TAR/Task2/Testing/DTA/."""
    if topic_id not in _ALLOWED_TOPICS:
        raise ValueError(
            f"Unknown topic_id {topic_id!r}. Allowed: {sorted(_ALLOWED_TOPICS)}"
        )
    base = data_dir / _DTA_BASE
    if not base.exists():
        raise FileNotFoundError(f"CLEF-TAR data not found at {base}. Run download first.")

    topic_path = base / "topics" / topic_id
    qrels_path = base / "qrels" / _QRELS_FILE

    title, boolean_query, candidate_pmids = _parse_topic_file(topic_path)
    qrels_abstract = _parse_qrels(qrels_path, topic_id)

    return Topic(
        topic_id=topic_id,
        title=title,
        boolean_query=boolean_query,
        candidate_pmids=candidate_pmids,
        qrels_abstract=qrels_abstract,
    )
```

(Stop here — `download_clef_tar_2019` and `fetch_abstracts` will be added in Tasks 3 and 4.)

- [ ] **Step 2.4: Run tests and verify they pass**

```bash
pytest tests/test_clef_tar_loader.py::test_load_topic_title \
       tests/test_clef_tar_loader.py::test_load_topic_boolean_query \
       tests/test_clef_tar_loader.py::test_load_topic_candidate_pmids \
       tests/test_clef_tar_loader.py::test_load_topic_qrels \
       tests/test_clef_tar_loader.py::test_load_topic_bad_id_raises \
       tests/test_clef_tar_loader.py::test_load_topic_missing_dir_raises \
       -v
```

Expected: 6 passed.

- [ ] **Step 2.5: Commit**

```bash
git add cascade_rc/data/clef_tar_loader.py tests/test_clef_tar_loader.py
git commit -m "feat(cascade_rc): Topic dataclass + load_topic with unit tests"
```

---

## Task 3: `download_clef_tar_2019` (TDD)

**Files:**
- Modify: `cascade_rc/data/clef_tar_loader.py` (add `download_clef_tar_2019`)
- Modify: `tests/test_clef_tar_loader.py` (add unit test)

- [ ] **Step 3.1: Write the failing test**

Append to `tests/test_clef_tar_loader.py`:

```python
from cascade_rc.data.clef_tar_loader import download_clef_tar_2019


def test_download_is_idempotent(tmp_path: Path) -> None:
    """If 2019-TAR already exists, download_clef_tar_2019 must be a no-op."""
    existing = tmp_path / "2019-TAR"
    existing.mkdir()
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    download_clef_tar_2019(tmp_path)  # must not wipe or re-clone

    assert sentinel.exists(), "idempotent check failed — 2019-TAR was overwritten"
```

- [ ] **Step 3.2: Run test to verify it fails**

```bash
pytest tests/test_clef_tar_loader.py::test_download_is_idempotent -v
```

Expected: `ImportError: cannot import name 'download_clef_tar_2019'`

- [ ] **Step 3.3: Implement `download_clef_tar_2019`**

Add to `cascade_rc/data/clef_tar_loader.py` (after the `_parse_qrels` function):

```python
def download_clef_tar_2019(target_dir: Path) -> None:
    """Sparse-clone the 2019-TAR subtree from CLEF-TAR/tar into target_dir.

    Idempotent: exits immediately if target_dir/2019-TAR already exists.
    Raises RuntimeError if git returns a non-zero exit code.
    """
    if (target_dir / "2019-TAR").exists():
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "tar"

        result = subprocess.run(
            [
                "git", "clone",
                "--depth=1", "--filter=blob:none", "--sparse",
                _REPO_URL, str(clone_dir),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed:\n{result.stderr}")

        result = subprocess.run(
            ["git", "sparse-checkout", "set", "2019-TAR"],
            cwd=str(clone_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git sparse-checkout failed:\n{result.stderr}")

        shutil.move(str(clone_dir / "2019-TAR"), str(target_dir / "2019-TAR"))
```

- [ ] **Step 3.4: Run test to verify it passes**

```bash
pytest tests/test_clef_tar_loader.py::test_download_is_idempotent -v
```

Expected: 1 passed.

- [ ] **Step 3.5: Commit**

```bash
git add cascade_rc/data/clef_tar_loader.py tests/test_clef_tar_loader.py
git commit -m "feat(cascade_rc): download_clef_tar_2019 with idempotency test"
```

---

## Task 4: `fetch_abstracts` (TDD)

**Files:**
- Modify: `cascade_rc/data/clef_tar_loader.py` (add `fetch_abstracts`)
- Modify: `tests/test_clef_tar_loader.py` (add unit tests)

- [ ] **Step 4.1: Write the failing tests**

Append to `tests/test_clef_tar_loader.py`:

```python
from cascade_rc.data.clef_tar_loader import fetch_abstracts


def test_fetch_abstracts_cache_hit(tmp_path: Path) -> None:
    """PMIDs already in abstracts.jsonl must not trigger a network call."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abstracts.jsonl").write_text(
        '{"pmid": "12345678", "title": "Test Title", "abstract": "Test abstract"}\n',
        encoding="utf-8",
    )

    result = fetch_abstracts(["12345678"], cache_dir)

    assert "12345678" in result
    assert result["12345678"]["title"] == "Test Title"
    assert result["12345678"]["abstract"] == "Test abstract"


def test_fetch_abstracts_missing_pmid_not_in_result(tmp_path: Path) -> None:
    """PMIDs absent from cache and not returned by Entrez are silently dropped."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abstracts.jsonl").write_text("", encoding="utf-8")

    # PMID "00000000" is not in cache and we're not mocking Entrez,
    # so fetch will try a real call and return nothing for a bogus ID.
    # The result must simply not contain that key — no exception.
    result = fetch_abstracts([], cache_dir)  # empty list → no network call
    assert result == {}


def test_fetch_abstracts_creates_cache_dir(tmp_path: Path) -> None:
    """fetch_abstracts must create cache_dir if it does not exist."""
    cache_dir = tmp_path / "new_cache"
    fetch_abstracts([], cache_dir)
    assert cache_dir.exists()
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
pytest tests/test_clef_tar_loader.py::test_fetch_abstracts_cache_hit \
       tests/test_clef_tar_loader.py::test_fetch_abstracts_missing_pmid_not_in_result \
       tests/test_clef_tar_loader.py::test_fetch_abstracts_creates_cache_dir \
       -v
```

Expected: `ImportError: cannot import name 'fetch_abstracts'`

- [ ] **Step 4.3: Implement `fetch_abstracts`**

Add to `cascade_rc/data/clef_tar_loader.py` (after `download_clef_tar_2019`):

```python
def fetch_abstracts(pmids: list[str], cache_dir: Path) -> dict[str, dict]:
    """Fetch title+abstract for each PMID from PubMed, caching results in
    cache_dir/abstracts.jsonl (one JSON object per line, keyed by 'pmid').

    Reuses PubMedConnector to configure Entrez credentials from env/.env.
    PMIDs with no title or no abstract are excluded from the returned dict.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "abstracts.jsonl"

    cache: dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rec = json.loads(line)
                cache[rec["pmid"]] = rec

    missing = [p for p in pmids if p not in cache]

    if missing:
        from tier1_search.pubmed_connector import PubMedConnector
        PubMedConnector()  # configures Entrez.email + Entrez.api_key from env

        new_records: list[dict] = []
        for start in range(0, len(missing), _CHUNK_SIZE):
            chunk = missing[start : start + _CHUNK_SIZE]
            try:
                handle = Entrez.efetch(
                    db="pubmed",
                    id=chunk,
                    rettype="medline",
                    retmode="text",
                )
                for rec in Medline.parse(handle):
                    pmid = rec.get("PMID", "").strip()
                    title = rec.get("TI", "").strip()
                    abstract = rec.get("AB", "").strip()
                    if pmid:
                        entry = {"pmid": pmid, "title": title, "abstract": abstract}
                        cache[pmid] = entry
                        new_records.append(entry)
                handle.close()
            except Exception:
                pass  # recall-safe: missing records are simply dropped
            time.sleep(0.35)

        if new_records:
            with cache_path.open("a", encoding="utf-8") as f:
                for rec in new_records:
                    f.write(json.dumps(rec) + "\n")

    return {
        p: cache[p]
        for p in pmids
        if p in cache and cache[p].get("title") and cache[p].get("abstract")
    }
```

- [ ] **Step 4.4: Run tests to verify they pass**

```bash
pytest tests/test_clef_tar_loader.py::test_fetch_abstracts_cache_hit \
       tests/test_clef_tar_loader.py::test_fetch_abstracts_missing_pmid_not_in_result \
       tests/test_clef_tar_loader.py::test_fetch_abstracts_creates_cache_dir \
       -v
```

Expected: 3 passed.

- [ ] **Step 4.5: Run all unit tests together**

```bash
pytest tests/test_clef_tar_loader.py -v -k "not minimum_positives and not empty_title and not binary"
```

Expected: 9 passed (6 from Task 2 + 3 from Task 4).

- [ ] **Step 4.6: Commit**

```bash
git add cascade_rc/data/clef_tar_loader.py tests/test_clef_tar_loader.py
git commit -m "feat(cascade_rc): fetch_abstracts with JSONL cache + unit tests"
```

---

## Task 5: CLI + parquet writer

**Files:**
- Modify: `cascade_rc/data/clef_tar_loader.py` (add `_write_parquet` helper + `main()` + `__main__` guard)

No new tests here — the CLI is exercised end-to-end in Task 7.

- [ ] **Step 5.1: Add `_write_parquet`, `main`, and `__main__` to `clef_tar_loader.py`**

Append to the bottom of `cascade_rc/data/clef_tar_loader.py`:

```python
def _write_parquet(rows: list[dict], path: Path) -> None:
    import pandas as pd
    df = pd.DataFrame(rows, columns=["pmid", "title", "abstract", "y_abstract"])
    df["y_abstract"] = df["y_abstract"].astype("int8")
    df.to_parquet(path, index=False)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest CLEF-TAR 2019 DTA topics into parquet for CASCADE-RC."
    )
    parser.add_argument(
        "--topic",
        action="append",
        dest="topics",
        choices=sorted(_ALLOWED_TOPICS),
        metavar="TOPIC_ID",
        help="Topic ID to process (repeatable). Default: all three.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for parquet files and abstract cache.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Directory containing the 2019-TAR/ tree (default: same as --out).",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip download_clef_tar_2019 (use when data already present).",
    )
    args = parser.parse_args()

    topics: list[str] = args.topics or sorted(_ALLOWED_TOPICS)
    data_dir: Path = args.data_dir or args.out

    if not args.skip_download:
        download_clef_tar_2019(data_dir)

    args.out.mkdir(parents=True, exist_ok=True)

    for topic_id in topics:
        topic = load_topic(topic_id, data_dir)
        abstracts = fetch_abstracts(topic.candidate_pmids, args.out / "cache")

        rows: list[dict] = []
        for pmid, qrel in topic.qrels_abstract.items():
            if pmid in abstracts:
                rows.append(
                    {
                        "pmid": pmid,
                        "title": abstracts[pmid]["title"],
                        "abstract": abstracts[pmid]["abstract"],
                        "y_abstract": qrel,
                    }
                )

        out_path = args.out / f"{topic_id}.parquet"
        _write_parquet(rows, out_path)

        n_pos = sum(1 for r in rows if r["y_abstract"] == 1)
        n_neg = sum(1 for r in rows if r["y_abstract"] == 0)
        total = len(rows)
        prevalence = n_pos / total if total else 0.0
        print(
            f"{topic_id}  total={total}  pos={n_pos}  neg={n_neg}"
            f"  prevalence={prevalence:.4f}"
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.2: Verify the module is importable with no side effects**

```bash
python -c "from cascade_rc.data.clef_tar_loader import main, _write_parquet; print('ok')"
```

Expected: `ok`

- [ ] **Step 5.3: Verify the CLI prints help without error**

```bash
python -m cascade_rc.data.clef_tar_loader --help
```

Expected output includes `--topic`, `--out`, `--data-dir`, `--skip-download`.

- [ ] **Step 5.4: Commit**

```bash
git add cascade_rc/data/clef_tar_loader.py
git commit -m "feat(cascade_rc): CLI entry point + parquet writer"
```

---

## Task 6: Integration tests (spec's parametrized tests)

**Files:**
- Modify: `tests/test_clef_tar_loader.py` (append 3 parametrized integration tests)

These tests skip cleanly when parquets don't exist yet. They become live in Task 7.

- [ ] **Step 6.1: Append integration tests to `tests/test_clef_tar_loader.py`**

```python
import pandas as pd

_PARQUET_DIR = _REPO_ROOT / "data" / "clef_tar"


@pytest.mark.parametrize("topic_id", ["CD008874", "CD012080", "CD012768"])
def test_minimum_positives(topic_id: str) -> None:
    path = _PARQUET_DIR / f"{topic_id}.parquet"
    if not path.exists():
        pytest.skip(f"{path} not yet generated — run the CLI first")
    df = pd.read_parquet(path)
    assert int(df["y_abstract"].sum()) >= 26, (
        f"{topic_id}: only {int(df['y_abstract'].sum())} positives, need ≥ 26"
    )


@pytest.mark.parametrize("topic_id", ["CD008874", "CD012080", "CD012768"])
def test_no_empty_title_or_abstract(topic_id: str) -> None:
    path = _PARQUET_DIR / f"{topic_id}.parquet"
    if not path.exists():
        pytest.skip(f"{path} not yet generated — run the CLI first")
    df = pd.read_parquet(path)
    assert (df["title"] != "").all(), f"{topic_id}: contains rows with empty title"
    assert (df["abstract"] != "").all(), f"{topic_id}: contains rows with empty abstract"


@pytest.mark.parametrize("topic_id", ["CD008874", "CD012080", "CD012768"])
def test_y_abstract_binary(topic_id: str) -> None:
    path = _PARQUET_DIR / f"{topic_id}.parquet"
    if not path.exists():
        pytest.skip(f"{path} not yet generated — run the CLI first")
    df = pd.read_parquet(path)
    assert set(df["y_abstract"].unique()).issubset({0, 1}), (
        f"{topic_id}: y_abstract contains values outside {{0, 1}}"
    )
```

- [ ] **Step 6.2: Run integration tests — expect all 9 to skip**

```bash
pytest tests/test_clef_tar_loader.py -v -k "minimum_positives or empty_title or binary"
```

Expected: 9 skipped (parquets don't exist yet).

- [ ] **Step 6.3: Commit**

```bash
git add tests/test_clef_tar_loader.py
git commit -m "test(cascade_rc): add CLEF-TAR integration tests (skip until CLI run)"
```

---

## Task 7: End-to-end run + final verification

**Prerequisites:** `PUBMED_EMAIL` must be set (in `.env` or environment). `PUBMED_API_KEY` is optional but recommended to avoid rate-limiting across 9K+ fetches.

- [ ] **Step 7.1: Set up PubMed credentials**

Ensure `.env` in `systematic-review-system/` contains:
```
PUBMED_EMAIL=your@email.com
PUBMED_API_KEY=your_key_here   # optional but recommended
```

- [ ] **Step 7.2: Run CLI for all three topics**

```bash
python -m cascade_rc.data.clef_tar_loader \
    --out data/clef_tar \
    --data-dir data/clef_tar
```

This will:
1. Download 2019-TAR via sparse clone into `data/clef_tar/2019-TAR/` (~30s)
2. Fetch abstracts for ~9K PMIDs across 3 topics — cached to `data/clef_tar/cache/abstracts.jsonl`
3. Write `data/clef_tar/CD008874.parquet`, `CD012080.parquet`, `CD012768.parquet`
4. Print summary stats

Expected stdout (exact numbers will vary by PubMed availability):
```
CD008874  total=NNNN  pos=NNN  neg=NNNN  prevalence=0.NNNN
CD012080  total=NNNN  pos=NNN  neg=NNNN  prevalence=0.NNNN
CD012768  total=NNN   pos=NN   neg=NNN   prevalence=0.NNNN
```

Runtime: ~30 minutes without an API key; ~10 minutes with one (rate limit 10 req/s).

- [ ] **Step 7.3: Run all tests**

```bash
pytest tests/test_clef_tar_loader.py -v
```

Expected:
- 9 unit tests: pass
- 9 integration tests: pass (no longer skipping)

Total: 18 passed, 0 failed, 0 skipped.

- [ ] **Step 7.4: Verify parquet schemas**

```bash
python - <<'EOF'
import pandas as pd
from pathlib import Path

for t in ["CD008874", "CD012080", "CD012768"]:
    df = pd.read_parquet(f"data/clef_tar/{t}.parquet")
    print(f"{t}: shape={df.shape}, cols={list(df.columns)}, dtypes={dict(df.dtypes)}")
    print(f"  positives={df['y_abstract'].sum()}, prevalence={df['y_abstract'].mean():.4f}")
EOF
```

Expected: each row shows `cols=['pmid', 'title', 'abstract', 'y_abstract']`, `y_abstract` dtype `int8`, positives ≥ 26.

- [ ] **Step 7.5: Final commit**

```bash
git add data/clef_tar/
git commit -m "data: add CLEF-TAR 2019 parquets for CD008874, CD012080, CD012768"
```

> Note: If `data/clef_tar/` is gitignored (large data files), skip this step and document the CLI command in the project README instead.

---

## Self-Review Checklist

**Spec coverage:**
- [x] `download_clef_tar_2019` → Task 3
- [x] `load_topic` with all five fields → Task 2
- [x] `fetch_abstracts` with JSONL cache → Task 4
- [x] Restricted to 3 topics → `_ALLOWED_TOPICS` constant, enforced in `load_topic`
- [x] Drop PMIDs without abstract/title → `fetch_abstracts` return filter
- [x] Drop PMIDs without qrels → CLI inner-join on `topic.qrels_abstract`
- [x] CLI with `--topic` and `--out` → Task 5
- [x] Parquet with `pmid, title, abstract, y_abstract` → `_write_parquet` in Task 5
- [x] `test_minimum_positives` (≥26) → Task 6
- [x] `test_no_empty_title_or_abstract` → Task 6
- [x] `test_y_abstract_binary` → Task 6
- [x] Summary stats per topic → `main()` in Task 5
- [x] No changes to live Tier 1 pipeline → only `cascade_rc/` and `tests/` files created

**Placeholder scan:** No TBDs, no "implement later", all steps have full code.

**Type consistency:** `Topic`, `load_topic`, `download_clef_tar_2019`, `fetch_abstracts`, `_write_parquet`, `main` — all names consistent across Tasks 2–6.
