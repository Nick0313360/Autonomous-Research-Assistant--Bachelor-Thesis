"""
cascade_rc/cache/sqlite_cache.py
==================================
Thread-safe SQLite cache for LLM ensemble responses.

One row per (model_id, prompt_sha, pmid, temperature, seed_b, template_v).
INSERT OR IGNORE gives idempotency; WAL mode gives concurrent reader safety.

CLI usage:
    python -m cascade_rc.cache.sqlite_cache merge \\
        --topics CD008874 CD012080 CD012768 CD011768 CD011975 CD011145 \\
        --cache-dir artefacts/cascade_rc/llm_cache \\
        --output artefacts/cascade_rc/llm_cache_merged.db

    python -m cascade_rc.cache.sqlite_cache migrate \\
        --source artefacts/cascade_rc/llm_cache.db \\
        --output-dir artefacts/cascade_rc/llm_cache \\
        --parquet-dir artefacts/cascade_rc/data
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
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._local: threading.local = threading.local()
        conn = self._connection()
        conn.executescript(self.SCHEMA)
        conn.commit()

    @classmethod
    def for_topic(cls, topic_id: str, cache_dir: Path) -> "SQLiteEnsembleCache":
        """Convenience constructor that gives each topic its own SQLite file.

        Each topic gets: cache_dir/llm_cache_{topic_id}.db
        Eliminates write contention when topics run in parallel.
        """
        return cls(Path(cache_dir) / f"llm_cache_{topic_id}.db")

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

    def purge_empty_responses(self) -> int:
        """Delete rows where response is '{}', empty string, or NULL.

        These are failed API calls that were cached before the LLM returned a
        valid JSON payload.  Purging them allows score_u to retry the affected
        PMID/seed slots on the next run.

        Returns:
            Number of rows deleted.
        """
        conn = self._connection()
        cur = conn.execute(
            "DELETE FROM llm_calls WHERE response='{}' OR response='' OR response IS NULL"
        )
        deleted = cur.rowcount
        conn.commit()
        return deleted

    def close(self) -> None:
        """Close thread-local connection; flushes WAL sidecars (.db-wal, .db-shm)."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None


# ---------------------------------------------------------------------------
# Module-level helpers: merge and migrate
# ---------------------------------------------------------------------------

_VERDICT_LABEL: dict[int, str] = {0: "Exclude", 1: "Include", 2: "Uncertain"}

_INSERT_SQL = """
    INSERT OR IGNORE INTO llm_calls
        (model_id, prompt_sha, pmid, temperature, seed_b, template_v,
         response, verdict, vote_label, created_at)
    VALUES (?,?,?,?,?,?,?,?,?,?)
"""


def _read_rows(path: Path) -> list[tuple]:
    """Read all llm_calls rows from *path*, returning (model_id, ..., created_at) tuples.

    Synthesises vote_label from verdict when the source DB pre-dates that column.
    """
    conn = sqlite3.connect(str(path))
    pragma = conn.execute("PRAGMA table_info(llm_calls)").fetchall()
    columns = [row[1] for row in pragma]
    has_vote_label = "vote_label" in columns

    if has_vote_label:
        rows = conn.execute(
            "SELECT model_id, prompt_sha, pmid, temperature, seed_b, template_v,"
            " response, verdict, vote_label, created_at FROM llm_calls"
        ).fetchall()
    else:
        raw = conn.execute(
            "SELECT model_id, prompt_sha, pmid, temperature, seed_b, template_v,"
            " response, verdict, created_at FROM llm_calls"
        ).fetchall()
        # synthesise vote_label between verdict and created_at
        rows = [r[:8] + (_VERDICT_LABEL.get(r[7], "Uncertain"),) + r[8:] for r in raw]

    conn.close()
    return rows


def merge_topic_caches(
    topic_ids: list[str],
    cache_dir: Path,
    output_path: Path,
) -> None:
    """Merge per-topic SQLite files into a single portable cache.

    Safe to run after all topics are complete. Uses INSERT OR IGNORE so any
    accidental overlap (there should be none — topics operate on disjoint PMIDs)
    is handled gracefully.
    """
    cache_dir = Path(cache_dir)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure merged DB has correct schema.
    merged_cache = SQLiteEnsembleCache(output_path)

    total_rows = 0
    for topic_id in topic_ids:
        src_path = cache_dir / f"llm_cache_{topic_id}.db"
        if not src_path.exists():
            print(f"  SKIP {topic_id}: cache not found at {src_path}")
            continue

        rows = _read_rows(src_path)
        dest_conn = sqlite3.connect(str(output_path))
        dest_conn.executemany(_INSERT_SQL, rows)
        dest_conn.commit()
        dest_conn.close()
        print(f"  Merged {len(rows):>6} rows from {topic_id}")
        total_rows += len(rows)

    stats = merged_cache.stats()
    print(
        f"  Done — {total_rows} rows inserted, "
        f"{stats['total_rows']} unique rows in merged cache"
    )


def migrate_to_per_topic(
    source_path: Path,
    output_dir: Path,
    parquet_dir: Path,
    topic_ids: list[str] | None = None,
) -> None:
    """Split a shared llm_cache.db into per-topic SQLite files.

    PMID → topic assignment is resolved by reading the topic parquets in
    *parquet_dir*.  Rows whose PMID does not appear in any parquet are skipped
    with a warning.

    Args:
        source_path:  Path to the original shared llm_cache.db.
        output_dir:   Directory that will receive llm_cache_{topic_id}.db files.
        parquet_dir:  Directory containing {topic_id}.parquet files.
        topic_ids:    Topics to migrate; defaults to the six CLEF-TAR topics.
    """
    import pandas as pd

    _DEFAULT_TOPICS = [
        "CD008874", "CD012080", "CD012768",
        "CD011768", "CD011975", "CD011145",
    ]
    if topic_ids is None:
        topic_ids = _DEFAULT_TOPICS

    source_path = Path(source_path)
    output_dir = Path(output_dir)
    parquet_dir = Path(parquet_dir)

    # Build pmid → topic_id mapping from parquets.
    pmid_to_topic: dict[str, str] = {}
    for topic_id in topic_ids:
        pq = parquet_dir / f"{topic_id}.parquet"
        if not pq.exists():
            print(f"  WARNING: {pq} not found — {topic_id} PMIDs won't be mapped")
            continue
        df = pd.read_parquet(pq, columns=["pmid"])
        for pmid in df["pmid"].astype(str):
            pmid_to_topic[pmid] = topic_id

    print(f"  PMID mapping: {len(pmid_to_topic)} PMIDs across {len(topic_ids)} topics")

    # Read the whole source DB once.
    rows = _read_rows(source_path)
    print(f"  Source: {len(rows)} rows from {source_path}")

    # Partition rows by topic.
    rows_by_topic: dict[str, list[tuple]] = {t: [] for t in topic_ids}
    unmapped = 0
    for row in rows:
        pmid = str(row[2])  # column order: model_id, prompt_sha, pmid, ...
        topic_id = pmid_to_topic.get(pmid)
        if topic_id is None:
            unmapped += 1
            continue
        rows_by_topic[topic_id].append(row)

    if unmapped:
        print(f"  WARNING: {unmapped} rows had unrecognised PMIDs and were skipped")

    # Write per-topic DBs.
    output_dir.mkdir(parents=True, exist_ok=True)
    for topic_id in topic_ids:
        topic_rows = rows_by_topic.get(topic_id, [])
        if not topic_rows:
            print(f"  SKIP {topic_id}: no rows to migrate")
            continue
        dest_cache = SQLiteEnsembleCache.for_topic(topic_id, output_dir)
        dest_conn = sqlite3.connect(str(dest_cache._path))
        dest_conn.executemany(_INSERT_SQL, topic_rows)
        dest_conn.commit()
        dest_conn.close()
        print(f"  Migrated {len(topic_rows):>6} rows → {dest_cache._path}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    _DEFAULT_TOPICS = [
        "CD008874", "CD012080", "CD012768",
        "CD011768", "CD011975", "CD011145",
    ]

    parser = argparse.ArgumentParser(
        description="SQLiteEnsembleCache utilities: merge and migrate per-topic DBs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- merge ---
    p_merge = sub.add_parser(
        "merge",
        help="Merge per-topic SQLite files into one portable cache",
    )
    p_merge.add_argument(
        "--topics", nargs="+", default=_DEFAULT_TOPICS, metavar="TOPIC_ID",
    )
    p_merge.add_argument(
        "--cache-dir", type=Path,
        default=Path("artefacts/cascade_rc/llm_cache"),
        help="Directory containing llm_cache_{topic_id}.db files",
    )
    p_merge.add_argument(
        "--output", type=Path,
        default=Path("artefacts/cascade_rc/llm_cache_merged.db"),
        help="Output path for the merged cache",
    )

    # --- migrate ---
    p_mig = sub.add_parser(
        "migrate",
        help="Split a shared llm_cache.db into per-topic SQLite files",
    )
    p_mig.add_argument(
        "--source", type=Path,
        default=Path("artefacts/cascade_rc/llm_cache.db"),
        help="Path to the original shared SQLite cache",
    )
    p_mig.add_argument(
        "--output-dir", type=Path,
        default=Path("artefacts/cascade_rc/llm_cache"),
        help="Directory to write llm_cache_{topic_id}.db files",
    )
    p_mig.add_argument(
        "--parquet-dir", type=Path,
        default=Path("artefacts/cascade_rc/data"),
        help="Directory containing {topic_id}.parquet files for PMID→topic mapping",
    )
    p_mig.add_argument(
        "--topics", nargs="+", default=_DEFAULT_TOPICS, metavar="TOPIC_ID",
    )

    args = parser.parse_args()

    if args.command == "merge":
        print(f"Merging {len(args.topics)} topic caches → {args.output}")
        merge_topic_caches(
            topic_ids=args.topics,
            cache_dir=args.cache_dir,
            output_path=args.output,
        )
    elif args.command == "migrate":
        if not args.source.exists():
            print(f"ERROR: source cache not found: {args.source}", file=sys.stderr)
            sys.exit(1)
        print(f"Migrating {args.source} → per-topic files in {args.output_dir}")
        migrate_to_per_topic(
            source_path=args.source,
            output_dir=args.output_dir,
            parquet_dir=args.parquet_dir,
            topic_ids=args.topics,
        )
