"""CLI utility: delete cached rows whose response payload is empty ('{}' or '').

These rows result from LLM API calls that returned no usable JSON.  They are
stored with verdict=2 (Uncertain) and block the score_u step from retrying,
because score_u treats any cache hit as valid.  Purging them forces a fresh
LLM call on the next score_u run.

Usage:
    python -m cascade_rc.cache.purge_empty
    python -m cascade_rc.cache.purge_empty --db path/to/llm_cache.db
    python -m cascade_rc.cache.purge_empty --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purge empty-response rows from the LLM ensemble cache.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("artefacts/cascade_rc/llm_cache.db"),
        help="Path to the SQLite cache database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many rows would be deleted without deleting them.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"ERROR: database not found at {args.db}", file=sys.stderr)
        sys.exit(1)

    from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache

    cache = SQLiteEnsembleCache(args.db)

    if args.dry_run:
        import sqlite3
        con = sqlite3.connect(str(args.db))
        n = con.execute(
            "SELECT COUNT(*) FROM llm_calls WHERE response='{}' OR response='' OR response IS NULL"
        ).fetchone()[0]
        con.close()
        print(f"DRY RUN — would delete {n} empty-response rows.")
        stats = cache.stats()
        print(f"Current stats: {json.dumps(stats, indent=2)}")
        cache.close()
        return

    before = cache.stats()
    n_deleted = cache.purge_empty_responses()
    after = cache.stats()
    cache.close()

    print(f"Purged {n_deleted} empty-response rows.")
    print(f"Rows before: {before['total_rows']}  →  after: {after['total_rows']}")
    print(f"Remaining stats: {json.dumps(after, indent=2)}")


if __name__ == "__main__":
    main()
