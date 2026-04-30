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
