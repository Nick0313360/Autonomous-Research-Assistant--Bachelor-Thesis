# Ensemble Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a crash-resumable SQLite cache to the B=5 ensemble screener so that killing and restarting a run costs zero new LLM calls for already-completed slots.

**Architecture:** `SQLiteEnsembleCache` (WAL-mode SQLite, per-thread connections) stores one row per `(model_id, prompt_sha, pmid, temperature, seed_b, template_v)`. `screen_abstract_ensemble` switches from a parallel `asyncio.gather` to a sequential per-slot loop that checks the cache first; cache misses call the LLM and populate the row. An offline driver (`__main__` block) wires topic loading + PubMed fetch + ensemble loop with `--dry-run`, `--resume-from-pmid`, and `--max-failures`.

**Tech Stack:** Python 3.11, sqlite3 (stdlib), hashlib (stdlib), threading.local (stdlib), asyncio, tqdm, aiohttp (already in deps via pubmed_fetch), infrastructure.llm_client.LLMClient

**Spec:** `docs/superpowers/specs/2026-04-30-ensemble-cache-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `cascade_rc/cache/sqlite_cache.py` | `SQLiteEnsembleCache` class |
| Create | `cascade_rc/tests/test_sqlite_cache.py` | Cache unit + integration tests |
| Create | `cascade_rc/tests/test_llm_ensemble.py` | Ensemble voting + cache-integration tests |
| Modify | `cascade_rc/cache/llm_ensemble.py` | Add cache integration, refactor voting logic, add offline driver |

---

## Task 1: `SQLiteEnsembleCache` — schema, `__init__`, `put()` → `test_idempotency`

**Files:**
- Create: `cascade_rc/tests/test_sqlite_cache.py`
- Create: `cascade_rc/cache/sqlite_cache.py`

- [ ] **Step 1: Write the failing test**

Create `cascade_rc/tests/test_sqlite_cache.py`:

```python
"""Tests for cascade_rc/cache/sqlite_cache.py."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache


_BASE_KEY = dict(
    model_id="gpt-oss:120b",
    prompt_sha="abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
    pmid="12345678",
    temperature=0.7,
    seed_b=0,
    template_v="v1",
)


def test_idempotency(tmp_path: Path) -> None:
    """INSERT OR IGNORE: calling put() twice with identical key inserts only one row."""
    cache = SQLiteEnsembleCache(tmp_path / "test.db")
    for _ in range(2):
        cache.put(
            **_BASE_KEY,
            response={"satisfies": True},
            verdict=1,
            vote_label="Include",
        )
    cache.close()

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    count = conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0]
    conn.close()
    assert count == 1
```

- [ ] **Step 2: Run it to see it fail**

```bash
cd /Users/nikitagolovanov/Documents/GitHub/Autonomous-Research-Assistant--Bachelor-Thesis/systematic-review-system
python -m pytest cascade_rc/tests/test_sqlite_cache.py::test_idempotency -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'cascade_rc.cache.sqlite_cache'`

- [ ] **Step 3: Create `cascade_rc/cache/sqlite_cache.py`**

```python
"""
cascade_rc/cache/sqlite_cache.py
==================================
Thread-safe SQLite cache for LLM ensemble responses.

One row per (model_id, prompt_sha, pmid, temperature, seed_b, template_v).
INSERT OR IGNORE gives idempotency; WAL mode gives concurrent reader safety.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SQLiteEnsembleCache:
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS llm_calls (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id    TEXT    NOT NULL,
        prompt_sha  TEXT    NOT NULL,   -- sha256 of rendered prompt (correctness invalidation)
        pmid        TEXT    NOT NULL,
        temperature REAL    NOT NULL,
        seed_b      INTEGER NOT NULL,   -- slot index 0..B-1 (cache discriminator only, NOT passed to LLM)
        template_v  TEXT    NOT NULL,   -- human-readable version tag (ablation filtering, e.g. WHERE template_v='v2')
        response    TEXT    NOT NULL,   -- raw JSON string from LLM
        verdict     INTEGER NOT NULL,   -- 0=Exclude, 1=Include, 2=Uncertain
        vote_label  TEXT    NOT NULL,   -- "Exclude" | "Include" | "Uncertain" (lossless round-trip)
        created_at  TEXT    NOT NULL,   -- ISO-8601 UTC: datetime.now(timezone.utc).isoformat()
        -- prompt_sha invalidates on any template edit; template_v enables human-readable
        -- ablation queries without juggling SHAs. Both columns serve different consumers.
        UNIQUE(model_id, prompt_sha, pmid, temperature, seed_b, template_v)
    );
    CREATE INDEX IF NOT EXISTS ix_pmid ON llm_calls(pmid);
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._local: threading.local = threading.local()
        conn = self._connection()
        conn.executescript(self.SCHEMA)
        conn.commit()

    def _connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def put(
        self,
        *,
        model_id: str,
        prompt_sha: str,
        pmid: str,
        temperature: float,
        seed_b: int,
        template_v: str,
        response: dict[str, Any],
        verdict: int,
        vote_label: str,
    ) -> None:
        """INSERT OR IGNORE — idempotent; safe to call on retry."""
        conn = self._connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO llm_calls
                (model_id, prompt_sha, pmid, temperature, seed_b, template_v,
                 response, verdict, vote_label, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_id,
                prompt_sha,
                pmid,
                temperature,
                seed_b,
                template_v,
                json.dumps(response),
                verdict,
                vote_label,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()

    def close(self) -> None:
        """Close thread-local connection; flushes WAL sidecars (.db-wal, .db-shm)."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest cascade_rc/tests/test_sqlite_cache.py::test_idempotency -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/cache/sqlite_cache.py cascade_rc/tests/test_sqlite_cache.py
git commit -m "feat(cache): SQLiteEnsembleCache skeleton with put() and idempotency test"
```

---

## Task 2: `get()`, `close()` → `test_vote_label_roundtrip`, `test_close_flushes_wal`

**Files:**
- Modify: `cascade_rc/cache/sqlite_cache.py` (add `get()`)
- Modify: `cascade_rc/tests/test_sqlite_cache.py` (add two tests)

- [ ] **Step 1: Write the failing tests**

Append to `cascade_rc/tests/test_sqlite_cache.py`:

```python
def test_vote_label_roundtrip(tmp_path: Path) -> None:
    """All three verdict/vote_label pairs survive a put→get round-trip."""
    cache = SQLiteEnsembleCache(tmp_path / "test.db")
    cases = [
        (1, "Include"),
        (0, "Exclude"),
        (2, "Uncertain"),
    ]
    for seed_b, (verdict, label) in enumerate(cases):
        cache.put(
            model_id="gpt-oss:120b",
            prompt_sha="sha_roundtrip",
            pmid="99999999",
            temperature=0.7,
            seed_b=seed_b,
            template_v="v1",
            response={"satisfies": True},
            verdict=verdict,
            vote_label=label,
        )

    for seed_b, (verdict, label) in enumerate(cases):
        row = cache.get(
            model_id="gpt-oss:120b",
            prompt_sha="sha_roundtrip",
            pmid="99999999",
            temperature=0.7,
            seed_b=seed_b,
            template_v="v1",
        )
        assert row is not None, f"seed_b={seed_b} not found"
        assert row["verdict"] == verdict
        assert row["vote_label"] == label

    cache.close()


def test_close_flushes_wal(tmp_path: Path) -> None:
    """After close(), no .db-wal or .db-shm sidecars remain on disk."""
    db_path = tmp_path / "test.db"
    cache = SQLiteEnsembleCache(db_path)
    cache.put(
        model_id="gpt-oss:120b",
        prompt_sha="sha_wal",
        pmid="11111111",
        temperature=0.7,
        seed_b=0,
        template_v="v1",
        response={"satisfies": True},
        verdict=1,
        vote_label="Include",
    )
    cache.close()
    assert not (tmp_path / "test.db-wal").exists(), ".db-wal sidecar found after close()"
    assert not (tmp_path / "test.db-shm").exists(), ".db-shm sidecar found after close()"
```

- [ ] **Step 2: Run to see them fail**

```bash
python -m pytest cascade_rc/tests/test_sqlite_cache.py::test_vote_label_roundtrip cascade_rc/tests/test_sqlite_cache.py::test_close_flushes_wal -v
```

Expected: both `FAILED` — `AttributeError: 'SQLiteEnsembleCache' object has no attribute 'get'`

- [ ] **Step 3: Add `get()` to `sqlite_cache.py`**

In `cascade_rc/cache/sqlite_cache.py`, add this method after `put()`, before `close()`:

```python
    def get(
        self,
        *,
        model_id: str,
        prompt_sha: str,
        pmid: str,
        temperature: float,
        seed_b: int,
        template_v: str,
    ) -> dict[str, Any] | None:
        """Return stored row as dict (with response parsed to dict) or None on miss."""
        row = self._connection().execute(
            """
            SELECT response, verdict, vote_label, created_at
            FROM llm_calls
            WHERE model_id=? AND prompt_sha=? AND pmid=?
              AND temperature=? AND seed_b=? AND template_v=?
            """,
            (model_id, prompt_sha, pmid, temperature, seed_b, template_v),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        try:
            d["response"] = json.loads(d["response"])
        except (json.JSONDecodeError, TypeError):
            pass
        return d
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest cascade_rc/tests/test_sqlite_cache.py::test_vote_label_roundtrip cascade_rc/tests/test_sqlite_cache.py::test_close_flushes_wal -v
```

Expected: both `PASSED`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/cache/sqlite_cache.py cascade_rc/tests/test_sqlite_cache.py
git commit -m "feat(cache): add get(), verify vote_label roundtrip and WAL close"
```

---

## Task 3: `fetch_ensemble()`, `stats()`, `test_concurrent_writes`

**Files:**
- Modify: `cascade_rc/cache/sqlite_cache.py` (add `fetch_ensemble()`, `stats()`)
- Modify: `cascade_rc/tests/test_sqlite_cache.py` (add `test_concurrent_writes`)

- [ ] **Step 1: Write the failing test**

Append to `cascade_rc/tests/test_sqlite_cache.py`:

```python
def test_concurrent_writes(tmp_path: Path) -> None:
    """Two threads writing different keys: no exceptions, both rows present."""
    import threading

    cache = SQLiteEnsembleCache(tmp_path / "test.db")
    errors: list[Exception] = []

    def _write(seed_b: int) -> None:
        try:
            cache.put(
                model_id="gpt-oss:120b",
                prompt_sha="sha_concurrent",
                pmid="77777777",
                temperature=0.7,
                seed_b=seed_b,
                template_v="v1",
                response={"satisfies": True},
                verdict=1,
                vote_label="Include",
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_write, args=(0,))
    t2 = threading.Thread(target=_write, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Thread errors: {errors}"

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    count = conn.execute(
        "SELECT COUNT(*) FROM llm_calls WHERE pmid='77777777'"
    ).fetchone()[0]
    conn.close()
    cache.close()
    assert count == 2


def test_stats_rows_per_seed_b(tmp_path: Path) -> None:
    """stats() returns correct total_rows, unique_pmids, rows_per_seed_b."""
    cache = SQLiteEnsembleCache(tmp_path / "test.db")
    for seed_b in range(5):
        cache.put(
            model_id="gpt-oss:120b",
            prompt_sha="sha_stats",
            pmid="44444444",
            temperature=0.7,
            seed_b=seed_b,
            template_v="v1",
            response={},
            verdict=1,
            vote_label="Include",
        )
    s = cache.stats()
    assert s["total_rows"] == 5
    assert s["unique_pmids"] == 1
    assert s["rows_per_seed_b"] == {"0": 1, "1": 1, "2": 1, "3": 1, "4": 1}
    cache.close()
```

- [ ] **Step 2: Run to see them fail**

```bash
python -m pytest cascade_rc/tests/test_sqlite_cache.py::test_concurrent_writes cascade_rc/tests/test_sqlite_cache.py::test_stats_rows_per_seed_b -v
```

Expected: both `FAILED` — `AttributeError: ... has no attribute 'stats'`

- [ ] **Step 3: Add `fetch_ensemble()` and `stats()` to `sqlite_cache.py`**

In `cascade_rc/cache/sqlite_cache.py`, add after `get()`, before `close()`:

```python
    def fetch_ensemble(
        self,
        *,
        model_id: str,
        prompt_sha: str,
        pmid: str,
        temperature: float,
        template_v: str,
        B: int,
    ) -> list[dict[str, Any]]:
        """Return up to B cached rows for this (model, prompt, pmid, temp, template), ordered by seed_b."""
        rows = self._connection().execute(
            """
            SELECT response, verdict, vote_label, seed_b, created_at
            FROM llm_calls
            WHERE model_id=? AND prompt_sha=? AND pmid=?
              AND temperature=? AND template_v=?
            ORDER BY seed_b
            LIMIT ?
            """,
            (model_id, prompt_sha, pmid, temperature, template_v, B),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["response"] = json.loads(d["response"])
            except (json.JSONDecodeError, TypeError):
                pass
            result.append(d)
        return result

    def stats(self) -> dict[str, Any]:
        """Return cache statistics: total_rows, unique_pmids, rows_per_seed_b."""
        conn = self._connection()
        total_rows: int = conn.execute(
            "SELECT COUNT(*) FROM llm_calls"
        ).fetchone()[0]
        unique_pmids: int = conn.execute(
            "SELECT COUNT(DISTINCT pmid) FROM llm_calls"
        ).fetchone()[0]
        seed_rows = conn.execute(
            "SELECT seed_b, COUNT(*) AS cnt FROM llm_calls GROUP BY seed_b ORDER BY seed_b"
        ).fetchall()
        rows_per_seed_b = {str(row["seed_b"]): row["cnt"] for row in seed_rows}
        return {
            "total_rows": total_rows,
            "unique_pmids": unique_pmids,
            "rows_per_seed_b": rows_per_seed_b,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest cascade_rc/tests/test_sqlite_cache.py -v
```

Expected: all `PASSED` (5 tests so far)

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/cache/sqlite_cache.py cascade_rc/tests/test_sqlite_cache.py
git commit -m "feat(cache): add fetch_ensemble(), stats(), concurrent_writes test"
```

---

## Task 4: Refactor `llm_ensemble.py` — triple return, vote helpers, new voting tests

**Files:**
- Modify: `cascade_rc/cache/llm_ensemble.py`
- Create: `cascade_rc/tests/test_llm_ensemble.py`

- [ ] **Step 1: Write the failing tests**

Create `cascade_rc/tests/test_llm_ensemble.py`:

```python
"""
cascade_rc/tests/test_llm_ensemble.py
========================================
Tests for the refactored _majority_and_u (triple return) and edge-case voting logic.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from infrastructure.llm_client import LLMResponse


_PICO = {
    "population": "patients with suspected knee injury",
    "intervention": "MRI",
    "comparator": "arthroscopy",
    "outcome": "diagnostic accuracy for meniscal tears",
    "study_design": "diagnostic test accuracy study",
}


def _resp(satisfies: bool | str) -> LLMResponse:
    parsed = {"satisfies": satisfies, "confidence": 0.9, "reasoning": "test"}
    return LLMResponse(
        content=str(parsed),
        model_used="gpt-oss:120b",
        input_tokens=20,
        output_tokens=10,
        latency_ms=50.0,
        parsed_json=parsed,
    )


def _mock_client(responses: list[LLMResponse]) -> MagicMock:
    client = MagicMock()
    client.GPT_MODEL = "gpt-oss:120b"
    client.complete = AsyncMock(side_effect=responses)
    return client


# ---------------------------------------------------------------------------
# Voting logic tests (no cache, no LLM)
# ---------------------------------------------------------------------------

def test_tie_uncertain_b5_2_2_1() -> None:
    """
    2 Include, 2 Exclude, 1 Uncertain → tie → majority='Uncertain', u=0.0, y_hat=0.

    Uncertain votes are excluded from the Include/Exclude binary competition, so
    Include=2 vs Exclude=2 is a tie. Tie resolves to Uncertain to force human review.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client(
        [_resp(True), _resp(True), _resp(False), _resp(False), _resp("uncertain")]
    )
    result = asyncio.run(
        screen_abstract_ensemble("T", "A", _PICO, n_calls=5, temperature=0.7, _client=client)
    )
    assert result.majority == "Uncertain"
    assert result.u == 0.0
    assert result.y_hat == 0


def test_tie_b4_genuine() -> None:
    """
    B=4, 2 Include, 2 Exclude → genuine tie → majority='Uncertain', u=0.0, y_hat=0.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client([_resp(True), _resp(True), _resp(False), _resp(False)])
    result = asyncio.run(
        screen_abstract_ensemble("T", "A", _PICO, n_calls=4, temperature=0.7, _client=client)
    )
    assert result.majority == "Uncertain"
    assert result.u == 0.0
    assert result.y_hat == 0


def test_b4_not_a_tie() -> None:
    """
    B=4, [Inc, Inc, Exc, Unc] is NOT a tie. Uncertain is excluded from competition:
    Include=2 vs Exclude=1 → Include wins. u = 2/4 = 0.5.

    This test explicitly prevents the regression of treating Uncertain as a tying vote.
    The original spec listed [Inc×2, Exc×1, Unc×1] as a B=4 tie — that is wrong.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client(
        [_resp(True), _resp(True), _resp(False), _resp("uncertain")]
    )
    result = asyncio.run(
        screen_abstract_ensemble("T", "A", _PICO, n_calls=4, temperature=0.7, _client=client)
    )
    assert result.majority == "Include"
    assert abs(result.u - 0.5) < 1e-9, f"Expected u=0.5, got {result.u}"
    assert result.y_hat == 1


def test_all_uncertain() -> None:
    """
    All 5 votes Uncertain (LLM completely unable to decide) → majority='Uncertain', u=0.0, y_hat=0.
    This is the pathological case that must always route to human review.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client([_resp("uncertain")] * 5)
    result = asyncio.run(
        screen_abstract_ensemble("T", "A", _PICO, n_calls=5, temperature=0.7, _client=client)
    )
    assert result.majority == "Uncertain"
    assert result.u == 0.0
    assert result.y_hat == 0
    assert result.votes.count("Uncertain") == 5
```

- [ ] **Step 2: Run to see them fail**

```bash
python -m pytest cascade_rc/tests/test_llm_ensemble.py -v
```

Expected: `FAILED` — the current `_majority_and_u` returns a 2-tuple; the parallel `asyncio.gather` path may pass, but the triple-return tests will fail after we add assertions on `y_hat`.

Actually these tests only check the final `EnsembleResult` fields — they may pass already if `y_hat` is computed from majority. Run to confirm current state before changing anything.

- [ ] **Step 3: Refactor `_majority_and_u` to return triple, add vote helpers**

In `cascade_rc/cache/llm_ensemble.py`:

1. Replace the existing `_majority_and_u` function with:

```python
def _vote_to_int(vote: Vote) -> int:
    """Map Vote label to integer: Include→1, Exclude→0, Uncertain→2."""
    if vote == "Include":
        return 1
    if vote == "Uncertain":
        return 2
    return 0


def _int_to_vote(v: int) -> Vote:
    """Map integer back to Vote label: 1→Include, 0→Exclude, 2→Uncertain."""
    if v == 1:
        return "Include"
    if v == 2:
        return "Uncertain"
    return "Exclude"


def _majority_and_u(votes: list[Vote], n: int) -> tuple[Vote, float, int]:
    """
    Compute majority label, self-consistency score u, and y_hat.

    Uncertain votes are excluded from the Include/Exclude binary competition.
    A tie (or all-Uncertain) resolves to majority='Uncertain', u=0.0, y_hat=0,
    which causes u < τ_SE and routes the abstract to human review.

    Returns (majority, u, y_hat).
    """
    include_count = votes.count("Include")
    exclude_count = votes.count("Exclude")

    if include_count > exclude_count:
        majority: Vote = "Include"
    elif exclude_count > include_count:
        majority = "Exclude"
    else:
        majority = "Uncertain"

    if majority == "Uncertain":
        return "Uncertain", 0.0, 0

    majority_count = include_count if majority == "Include" else exclude_count
    y_hat = 1 if majority == "Include" else 0
    return majority, majority_count / n, y_hat
```

2. Update the caller in `screen_abstract_ensemble` — replace these two lines:
```python
    majority, u = _majority_and_u(votes, n_calls)
    y_hat = 1 if majority == "Include" else 0
```
with:
```python
    majority, u, y_hat = _majority_and_u(votes, n_calls)
```

3. Add `import hashlib` to the imports at the top of the file.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest cascade_rc/tests/test_llm_ensemble.py tests/test_llm_ensemble.py -v
```

Expected: all `PASSED`. The root-level `tests/test_llm_ensemble.py` (existing tests from before this feature) must also still pass.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/cache/llm_ensemble.py cascade_rc/tests/test_llm_ensemble.py
git commit -m "feat(ensemble): triple return for _majority_and_u, add vote helpers and voting tests"
```

---

## Task 5: Cache integration in `screen_abstract_ensemble` → `test_cache_hit_skips_llm`, `test_partial_cache_completion`

**Files:**
- Modify: `cascade_rc/cache/llm_ensemble.py` (add `pmid`, `_cache`, `_model_id`, `_template_v` params; sequential loop)
- Modify: `cascade_rc/tests/test_llm_ensemble.py` (add two tests)

- [ ] **Step 1: Write the failing tests**

Append to `cascade_rc/tests/test_llm_ensemble.py`:

```python
# ---------------------------------------------------------------------------
# Cache integration tests
# ---------------------------------------------------------------------------

import hashlib

from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache
from tier2_screening.abstract_screener import _TEMPLATE, _fill_template
from cascade_rc.cache.llm_ensemble import _CRITERION_TEXT


def _make_prompt_sha(title: str, abstract: str, pico: dict) -> str:
    """Replicate the sha computation from screen_abstract_ensemble."""
    pico_text = (
        f"Population: {pico.get('population', '')}\n"
        f"Intervention: {pico.get('intervention', '')}\n"
        f"Comparator: {pico.get('comparator', '')}\n"
        f"Outcome: {pico.get('outcome', '')}\n"
        f"Study design: {pico.get('study_design', '')}"
    )
    prompt = _fill_template(
        _TEMPLATE,
        pico_text=pico_text,
        criterion_text=_CRITERION_TEXT,
        title=title,
        abstract=str(abstract)[:500],
    )
    return hashlib.sha256(prompt.encode()).hexdigest()


def test_cache_hit_skips_llm(tmp_path: Path) -> None:
    """All 5 slots pre-populated: client.complete is never called."""
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    cache = SQLiteEnsembleCache(tmp_path / "test.db")
    title, abstract, pmid = "Test Title", "Test abstract.", "12345678"
    prompt_sha = _make_prompt_sha(title, abstract, _PICO)

    for seed_b in range(5):
        cache.put(
            model_id="gpt-oss:120b",
            prompt_sha=prompt_sha,
            pmid=pmid,
            temperature=0.7,
            seed_b=seed_b,
            template_v="v1",
            response={"satisfies": True},
            verdict=1,
            vote_label="Include",
        )

    client = MagicMock()
    client.GPT_MODEL = "gpt-oss:120b"
    client.complete = AsyncMock(side_effect=Exception("should not be called"))

    result = asyncio.run(
        screen_abstract_ensemble(
            title, abstract, _PICO,
            pmid=pmid, n_calls=5, temperature=0.7,
            _client=client, _cache=cache, _template_v="v1",
        )
    )
    assert client.complete.call_count == 0
    assert len(result.votes) == 5
    assert result.majority == "Include"
    cache.close()


def test_partial_cache_completion(tmp_path: Path) -> None:
    """
    Slots 0, 2, 4 pre-populated: only slots 1 and 3 trigger LLM calls.
    Order is preserved: cached slot 0 appears at index 0, not appended last.
    This is the within-PMID resumability test (crash mid-ensemble scenario).
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    cache = SQLiteEnsembleCache(tmp_path / "test.db")
    title, abstract, pmid = "Partial Title", "Partial abstract.", "88888888"
    prompt_sha = _make_prompt_sha(title, abstract, _PICO)

    for seed_b in [0, 2, 4]:
        cache.put(
            model_id="gpt-oss:120b",
            prompt_sha=prompt_sha,
            pmid=pmid,
            temperature=0.7,
            seed_b=seed_b,
            template_v="v1",
            response={"satisfies": True},
            verdict=1,
            vote_label="Include",
        )

    client = _mock_client([_resp(True), _resp(True)])  # for slots 1 and 3

    result = asyncio.run(
        screen_abstract_ensemble(
            title, abstract, _PICO,
            pmid=pmid, n_calls=5, temperature=0.7,
            _client=client, _cache=cache, _template_v="v1",
        )
    )

    assert client.complete.call_count == 2, f"Expected 2 LLM calls, got {client.complete.call_count}"
    assert len(result.votes) == 5
    # Cached slots at indices 0, 2, 4 are Include; LLM slots 1, 3 also Include here
    assert result.votes[0] == "Include"  # cached
    assert result.votes[2] == "Include"  # cached
    assert result.votes[4] == "Include"  # cached
    cache.close()
```

- [ ] **Step 2: Run to see them fail**

```bash
python -m pytest cascade_rc/tests/test_llm_ensemble.py::test_cache_hit_skips_llm cascade_rc/tests/test_llm_ensemble.py::test_partial_cache_completion -v
```

Expected: `FAILED` — `screen_abstract_ensemble` does not yet accept `pmid` or `_cache`.

- [ ] **Step 3: Integrate cache into `screen_abstract_ensemble`**

Replace the entire `screen_abstract_ensemble` function in `cascade_rc/cache/llm_ensemble.py` with:

```python
async def screen_abstract_ensemble(
    title: str,
    abstract: str,
    pico: dict,
    pmid: str | None = None,
    n_calls: int = 5,
    temperature: float = 0.7,
    _client: Optional[Any] = None,
    _cache: Optional[Any] = None,
    _model_id: str = "gpt-oss:120b",
    _template_v: str = "v1",
) -> EnsembleResult:
    """
    Run B=n_calls stochastic screenings of one abstract and aggregate the votes.

    When pmid and _cache are both provided, each slot is looked up in the SQLite
    cache before calling the LLM. The sequential per-slot loop (replacing the former
    asyncio.gather) enables crash-resumable runs: a killed process costs zero extra
    LLM calls on restart for completed slots.

    Parameters
    ----------
    pmid : str | None
        PMID for cache keying. None disables caching (backwards-compatible).
    _cache : SQLiteEnsembleCache | None
        Injected cache instance. None disables caching.
    _model_id : str
        Model identifier stored in cache rows (default gpt-oss:120b).
    _template_v : str
        Template version tag for ablation filtering (default v1).
    """
    client = _client if _client is not None else LLMClient()

    pico_text = (
        f"Population: {pico.get('population', '')}\n"
        f"Intervention: {pico.get('intervention', '')}\n"
        f"Comparator: {pico.get('comparator', '')}\n"
        f"Outcome: {pico.get('outcome', '')}\n"
        f"Study design: {pico.get('study_design', '')}"
    )

    prompt = _fill_template(
        _TEMPLATE,
        pico_text=pico_text,
        criterion_text=_CRITERION_TEXT,
        title=title,
        abstract=str(abstract)[:500],
    )
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()

    use_cache = _cache is not None and pmid is not None
    votes: list[Vote] = []

    for b in range(n_calls):
        cached = None
        if use_cache:
            cached = _cache.get(
                model_id=_model_id,
                prompt_sha=prompt_sha,
                pmid=pmid,
                temperature=temperature,
                seed_b=b,
                template_v=_template_v,
            )

        if cached is not None:
            vote: Vote = cached["vote_label"]  # type: ignore[assignment]
            logger.info("cache_hit pmid=%s slot=%d", pmid, b)
        else:
            response = await client.complete(
                prompt=prompt,
                system=_SYSTEM,
                model=_model_id,
                temperature=temperature,
                max_tokens=128,
                response_format="json",
            )
            vote = _parse_vote(response.parsed_json)
            if use_cache:
                _cache.put(
                    model_id=_model_id,
                    prompt_sha=prompt_sha,
                    pmid=pmid,
                    temperature=temperature,
                    seed_b=b,
                    template_v=_template_v,
                    response=response.parsed_json or {},
                    verdict=_vote_to_int(vote),
                    vote_label=vote,
                )
            logger.info("cache_miss pmid=%s slot=%d vote=%s", pmid, b, vote)

        votes.append(vote)

    majority, u, y_hat = _majority_and_u(votes, n_calls)
    logger.debug("Ensemble: votes=%s majority=%s u=%.3f", votes, majority, u)
    return EnsembleResult(votes=votes, majority=majority, u=u, y_hat=y_hat)
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest cascade_rc/tests/test_llm_ensemble.py tests/test_llm_ensemble.py -v
```

Expected: all `PASSED` — new cache tests pass; existing root-level voting tests still pass.

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/cache/llm_ensemble.py cascade_rc/tests/test_llm_ensemble.py
git commit -m "feat(ensemble): integrate SQLiteEnsembleCache into screen_abstract_ensemble"
```

---

## Task 6: Integration tests — `test_resumability`, `test_seed_partition`

**Files:**
- Modify: `cascade_rc/tests/test_sqlite_cache.py` (add two integration tests)

- [ ] **Step 1: Write the failing tests**

Append to `cascade_rc/tests/test_sqlite_cache.py`:

```python
# ---------------------------------------------------------------------------
# Integration tests (cache + ensemble)
# ---------------------------------------------------------------------------

def test_resumability(tmp_path: Path) -> None:
    """
    Simulate a crash after 3/100 PMIDs, restart, assert 97×5=485 new LLM calls.

    Phase 1 ('pre-crash'): run ensemble for PMIDs 0-2 with a mock client.
                          This populates 15 cache rows (3 PMIDs × 5 slots).
    Phase 2 ('restart'):  fresh mock, run PMIDs 3-99 (97 PMIDs).
                          Each needs 5 LLM calls → 485 total.
    Phase 3 ('verify'):   run all 100 PMIDs again; assert zero new LLM calls
                          (every slot already cached).
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from infrastructure.llm_client import LLMResponse
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    def _resp(satisfies: bool) -> LLMResponse:
        parsed = {"satisfies": satisfies, "confidence": 0.9, "reasoning": "test"}
        return LLMResponse(
            content=str(parsed), model_used="gpt-oss:120b",
            input_tokens=10, output_tokens=5, latency_ms=20.0,
            parsed_json=parsed,
        )

    def _mock(n_responses: int) -> MagicMock:
        c = MagicMock()
        c.GPT_MODEL = "gpt-oss:120b"
        c.complete = AsyncMock(return_value=_resp(True))
        return c

    pico = {"population": "", "intervention": "", "comparator": "", "outcome": "", "study_design": ""}
    all_pmids = [f"{i:08d}" for i in range(100)]
    db_path = tmp_path / "resume.db"

    # Phase 1 — pre-crash: complete first 3 PMIDs
    cache = SQLiteEnsembleCache(db_path)
    client1 = _mock(15)
    for pmid in all_pmids[:3]:
        asyncio.run(
            screen_abstract_ensemble(
                "T", "A", pico, pmid=pmid, n_calls=5, temperature=0.7,
                _client=client1, _cache=cache, _template_v="v1",
            )
        )
    assert client1.complete.call_count == 15
    cache.close()

    # Phase 2 — restart: process remaining 97 PMIDs
    cache2 = SQLiteEnsembleCache(db_path)
    client2 = _mock(485)
    for pmid in all_pmids[3:]:
        asyncio.run(
            screen_abstract_ensemble(
                "T", "A", pico, pmid=pmid, n_calls=5, temperature=0.7,
                _client=client2, _cache=cache2, _template_v="v1",
            )
        )
    assert client2.complete.call_count == 97 * 5
    cache2.close()

    # Phase 3 — verify: re-run all 100; expect zero new calls
    cache3 = SQLiteEnsembleCache(db_path)
    client3 = MagicMock()
    client3.GPT_MODEL = "gpt-oss:120b"
    client3.complete = AsyncMock(side_effect=Exception("should not be called"))
    for pmid in all_pmids:
        asyncio.run(
            screen_abstract_ensemble(
                "T", "A", pico, pmid=pmid, n_calls=5, temperature=0.7,
                _client=client3, _cache=cache3, _template_v="v1",
            )
        )
    assert client3.complete.call_count == 0
    cache3.close()


def test_seed_partition(tmp_path: Path) -> None:
    """
    Populate all 5 slots, delete seed_b=2, re-run: exactly one LLM call (slot 2 only).
    Validates that slot-level independence is enforced by the cache key.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from infrastructure.llm_client import LLMResponse
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    def _resp(satisfies: bool) -> LLMResponse:
        parsed = {"satisfies": satisfies, "confidence": 0.9, "reasoning": "test"}
        return LLMResponse(
            content=str(parsed), model_used="gpt-oss:120b",
            input_tokens=10, output_tokens=5, latency_ms=20.0,
            parsed_json=parsed,
        )

    def _mock(responses: list[LLMResponse]) -> MagicMock:
        c = MagicMock()
        c.GPT_MODEL = "gpt-oss:120b"
        c.complete = AsyncMock(side_effect=responses)
        return c

    pico = {"population": "", "intervention": "", "comparator": "", "outcome": "", "study_design": ""}
    pmid = "55555555"
    db_path = tmp_path / "seed_part.db"

    # First run: populate all 5 slots
    cache = SQLiteEnsembleCache(db_path)
    client1 = _mock([_resp(True)] * 5)
    asyncio.run(
        screen_abstract_ensemble(
            "T", "A", pico, pmid=pmid, n_calls=5, temperature=0.7,
            _client=client1, _cache=cache, _template_v="v1",
        )
    )
    assert client1.complete.call_count == 5
    cache.close()

    # Delete only seed_b=2
    conn = sqlite3.connect(str(db_path))
    conn.execute("DELETE FROM llm_calls WHERE pmid=? AND seed_b=2", (pmid,))
    conn.commit()
    conn.close()

    # Re-run: only slot 2 should be re-called
    cache2 = SQLiteEnsembleCache(db_path)
    client2 = _mock([_resp(True)])  # exactly one response needed
    result = asyncio.run(
        screen_abstract_ensemble(
            "T", "A", pico, pmid=pmid, n_calls=5, temperature=0.7,
            _client=client2, _cache=cache2, _template_v="v1",
        )
    )
    assert client2.complete.call_count == 1, f"Expected 1 call, got {client2.complete.call_count}"
    assert len(result.votes) == 5
    cache2.close()
```

- [ ] **Step 2: Run to see them fail**

```bash
python -m pytest cascade_rc/tests/test_sqlite_cache.py::test_resumability cascade_rc/tests/test_sqlite_cache.py::test_seed_partition -v
```

Expected: tests are discovered and run (they may already pass given the cache integration is complete — verify).

- [ ] **Step 3: Confirm all cache tests pass**

```bash
python -m pytest cascade_rc/tests/test_sqlite_cache.py -v
```

Expected: all `PASSED` (7 tests)

- [ ] **Step 4: Commit**

```bash
git add cascade_rc/tests/test_sqlite_cache.py
git commit -m "test(cache): add resumability and seed_partition integration tests"
```

---

## Task 7: Offline driver (`__main__` block in `llm_ensemble.py`)

**Files:**
- Modify: `cascade_rc/cache/llm_ensemble.py` (add `__main__` block at bottom)

- [ ] **Step 1: Verify the dependencies are importable**

```bash
python -c "from cascade_rc.data.clef_tar_loader import load_topic; print('ok')"
python -c "from cascade_rc.data.pubmed_fetch import fetch_abstracts; print('ok')"
python -c "import tqdm; print('ok')"
```

If `tqdm` is missing: `pip install tqdm`

- [ ] **Step 2: Add the `__main__` block**

Append to the bottom of `cascade_rc/cache/llm_ensemble.py`:

```python
# ---------------------------------------------------------------------------
# Offline driver — populate cache for an entire CLEF-TAR topic
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import argparse
    import json
    import sys
    from pathlib import Path as _Path

    try:
        from tqdm import tqdm as _tqdm
    except ImportError:
        def _tqdm(it, **_):  # type: ignore[misc]
            return it

    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s %(name)s %(message)s")
    _driver_log = _logging.getLogger("cascade_rc.cache.llm_ensemble.__main__")

    from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache as _Cache
    from cascade_rc.config import CascadeRCConfig as _Cfg
    from cascade_rc.data.clef_tar_loader import (
        _DEFAULT_CACHE_DIR as _TAR_DIR,
        download_clef_tar_2019 as _download,
        load_topic as _load_topic,
    )
    from cascade_rc.data.pubmed_fetch import fetch_abstracts as _fetch

    _ap = argparse.ArgumentParser(
        description="Populate LLM ensemble cache for a CLEF-TAR topic."
    )
    _ap.add_argument("--topic", required=True, help="CLEF-TAR topic ID, e.g. CD012768")
    _ap.add_argument("--B", type=int, default=5, help="Ensemble size (default 5)")
    _ap.add_argument("--T", type=float, default=0.7, help="LLM temperature (default 0.7)")
    _ap.add_argument("--cache-path", type=_Path, default=None, help="Path to SQLite cache DB")
    _ap.add_argument("--template-v", default="v1", help="Template version tag")
    _ap.add_argument("--ncbi-email", default="", help="Email for NCBI API (required by NCBI ToS)")
    _ap.add_argument("--max-failures", type=int, default=10,
                     help="Abort after N consecutive PMID failures (default 10)")
    _ap.add_argument("--resume-from-pmid", default=None,
                     help="Skip PMIDs before this one in the candidate list")
    _ap.add_argument("--dry-run", action="store_true",
                     help="Report cache hit rate without making LLM calls, then exit")
    _args = _ap.parse_args()

    _cfg = _Cfg()
    _cache_path: _Path = _args.cache_path or _cfg.sqlite_cache_path
    _ncbi_email: str = _args.ncbi_email or _cfg.ncbi_email
    if not _ncbi_email:
        _driver_log.warning("No NCBI email provided; NCBI may throttle requests.")

    # Download CLEF-TAR data if not cached
    if not (_TAR_DIR / "2019-TAR").exists():
        _driver_log.info("Downloading CLEF-TAR data to %s …", _TAR_DIR)
        _download(_TAR_DIR)

    _topic = _load_topic(_args.topic, _TAR_DIR)
    _pmids: list[str] = _topic.candidate_pmids

    # Apply --resume-from-pmid
    if _args.resume_from_pmid is not None:
        try:
            _resume_idx = _pmids.index(_args.resume_from_pmid)
            _pmids = _pmids[_resume_idx:]
            _driver_log.info(
                "Resuming from PMID %s (skipping first %d)", _args.resume_from_pmid, _resume_idx
            )
        except ValueError:
            _driver_log.error(
                "--resume-from-pmid %s not found in topic candidate list", _args.resume_from_pmid
            )
            sys.exit(1)

    # Fetch abstracts via PubMed (per-PMID JSON cache in artefacts/)
    _driver_log.info("Fetching abstracts for %d PMIDs …", len(_pmids))
    _abstracts: dict = asyncio.run(
        _fetch(_pmids, email=_ncbi_email, api_key=_cfg.ncbi_api_key)
    )

    _valid_pmids = [
        p for p in _pmids
        if p in _abstracts and _abstracts[p].get("abstract")
    ]
    _skipped = len(_pmids) - len(_valid_pmids)
    if _skipped:
        _driver_log.warning("Skipping %d PMIDs with no abstract", _skipped)

    _cache = _Cache(_cache_path)
    _pico: dict = {
        "population": "", "intervention": "", "comparator": "", "outcome": "", "study_design": ""
    }

    # --dry-run: report cache completeness per PMID, exit without LLM calls
    if _args.dry_run:
        _hits = 0
        for _p in _valid_pmids:
            _rec = _abstracts[_p]
            _pico_text = (
                f"Population: \nIntervention: \nComparator: \n"
                f"Outcome: \nStudy design: "
            )
            _prompt = _fill_template(
                _TEMPLATE,
                pico_text=_pico_text,
                criterion_text=_CRITERION_TEXT,
                title=str(_rec.get("title", "")),
                abstract=str(_rec.get("abstract", ""))[:500],
            )
            _sha = hashlib.sha256(_prompt.encode()).hexdigest()
            _rows = _cache.fetch_ensemble(
                model_id=LLMClient.GPT_MODEL,
                prompt_sha=_sha,
                pmid=_p,
                temperature=_args.T,
                template_v=_args.template_v,
                B=_args.B,
            )
            if len(_rows) == _args.B:
                _hits += 1
        print(json.dumps({
            "topic": _args.topic,
            "total_valid_pmids": len(_valid_pmids),
            "fully_cached": _hits,
            "cache_hit_rate": _hits / len(_valid_pmids) if _valid_pmids else 0.0,
            "would_call_llm": (len(_valid_pmids) - _hits) * _args.B,
        }, indent=2))
        _cache.close()
        sys.exit(0)

    # Main loop
    _client = LLMClient()
    _failure_count = 0

    for _pmid in _tqdm(_valid_pmids, desc=f"Ensemble {_args.topic}"):
        _rec = _abstracts[_pmid]
        try:
            asyncio.run(
                screen_abstract_ensemble(
                    title=str(_rec.get("title", "")),
                    abstract=str(_rec.get("abstract", "")),
                    pico=_pico,
                    pmid=_pmid,
                    n_calls=_args.B,
                    temperature=_args.T,
                    _client=_client,
                    _cache=_cache,
                    _model_id=LLMClient.GPT_MODEL,
                    _template_v=_args.template_v,
                )
            )
            _failure_count = 0
        except sqlite3.Error as exc:
            _driver_log.error("PMID %s: structural cache error — aborting: %s", _pmid, exc)
            _cache.close()
            sys.exit(2)
        except Exception as exc:  # noqa: BLE001
            _failure_count += 1
            _driver_log.warning(
                "PMID %s: transient failure %d/%d: %s",
                _pmid, _failure_count, _args.max_failures, exc,
            )
            if _failure_count >= _args.max_failures:
                _driver_log.error(
                    "Aborting: %d consecutive failures exceeded --max-failures=%d",
                    _failure_count, _args.max_failures,
                )
                _cache.close()
                sys.exit(1)

    print(json.dumps(_cache.stats(), indent=2))
    _cache.close()
```

Also add `import sqlite3` to the top-level imports of `llm_ensemble.py` (needed for `sqlite3.Error` in the driver block).

- [ ] **Step 3: Verify driver help text**

```bash
python -m cascade_rc.cache.llm_ensemble --help
```

Expected: usage message with `--topic`, `--B`, `--T`, `--cache-path`, `--template-v`, `--ncbi-email`, `--max-failures`, `--resume-from-pmid`, `--dry-run`

- [ ] **Step 4: Run the full test suite**

```bash
python -m pytest cascade_rc/tests/ tests/test_llm_ensemble.py -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add cascade_rc/cache/llm_ensemble.py
git commit -m "feat(ensemble): add offline driver with --dry-run, --resume-from-pmid, --max-failures"
```

---

## Self-Review Checklist

Ran against spec `docs/superpowers/specs/2026-04-30-ensemble-cache-design.md`:

| Spec requirement | Task |
|---|---|
| `SQLiteEnsembleCache` with full schema | Task 1–3 |
| `verdict` 0/1/2 + `vote_label` TEXT (lossless) | Task 1, 2 |
| `prompt_sha` + `template_v` dual-column | Task 1 (schema comment) |
| `INSERT OR IGNORE` idempotency | Task 1 (`put()`) |
| `threading.local()` per-thread connection | Task 1 (`_connection()`) |
| WAL + NORMAL sync | Task 1 (`_connection()`) |
| `close()` flushes WAL sidecars | Task 2 |
| `fetch_ensemble()` | Task 3 |
| `stats()` with `rows_per_seed_b` | Task 3 |
| `test_concurrent_writes` | Task 3 |
| `_majority_and_u` returns triple | Task 4 |
| `_vote_to_int` / `_int_to_vote` helpers | Task 4 |
| `test_tie_uncertain_b5_2_2_1` | Task 4 |
| `test_tie_b4_genuine` | Task 4 |
| `test_b4_not_a_tie` (regression guard) | Task 4 |
| `test_all_uncertain` | Task 4 |
| `pmid=None` opt-out (backwards compat) | Task 5 |
| Sequential loop (no `asyncio.gather`) | Task 5 |
| `hashlib.sha256` prompt_sha | Task 5 |
| Structured log lines `cache_hit`/`cache_miss` | Task 5 |
| `test_cache_hit_skips_llm` | Task 5 |
| `test_partial_cache_completion` (within-PMID) | Task 5 |
| `test_resumability` (across-PMID) | Task 6 |
| `test_seed_partition` | Task 6 |
| Offline driver CLI flags | Task 7 |
| `--dry-run` mode | Task 7 |
| `--resume-from-pmid` flag | Task 7 |
| `--max-failures` with transient/structural split | Task 7 |
| `json.dumps(cache.stats())` final output | Task 7 |
| Fetch-on-the-fly via `load_topic` + `fetch_abstracts` | Task 7 |
| `created_at` ISO-8601 UTC | Task 1 (`put()`) |
