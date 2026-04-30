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
