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
