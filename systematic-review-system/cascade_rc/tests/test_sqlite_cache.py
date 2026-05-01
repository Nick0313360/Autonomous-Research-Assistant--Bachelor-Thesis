"""Tests for cascade_rc/cache/sqlite_cache.py."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

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
    assert (tmp_path / "test.db-wal").exists() or (tmp_path / "test.db-shm").exists(), \
        "Expected WAL sidecars before close() — WAL mode not activated?"
    cache.close()
    assert not (tmp_path / "test.db-wal").exists(), ".db-wal sidecar found after close()"
    assert not (tmp_path / "test.db-shm").exists(), ".db-shm sidecar found after close()"


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

    def _mock() -> MagicMock:
        c = MagicMock()
        c.GPT_MODEL = "gpt-oss:120b"
        c.complete = AsyncMock(return_value=_resp(True))
        return c

    pico = {"population": "", "intervention": "", "comparator": "", "outcome": "", "study_design": ""}
    all_pmids = [f"{i:08d}" for i in range(100)]
    db_path = tmp_path / "resume.db"

    # Phase 1 — pre-crash: complete first 3 PMIDs
    cache = SQLiteEnsembleCache(db_path)
    client1 = _mock()
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
    client2 = _mock()
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
