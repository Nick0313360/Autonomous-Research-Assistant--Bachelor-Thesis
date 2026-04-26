"""
infrastructure/logger.py
========================
Thread-safe SQLite audit log for every LLM decision in the pipeline.

Each row corresponds to one DecisionRecord.  inputs/outputs dicts and
flags list are serialised as JSON strings.  Enums are stored as their
.value strings so the database is human-readable without the codebase.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from models.data_classes import DecisionRecord, Stage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL schema
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS decisions (
    record_id           TEXT PRIMARY KEY,
    paper_id            TEXT    NOT NULL,
    stage               TEXT    NOT NULL,
    decision            TEXT    NOT NULL,
    confidence          REAL    NOT NULL,
    inputs              TEXT    NOT NULL,
    outputs             TEXT    NOT NULL,
    model_used          TEXT    NOT NULL,
    model_version       TEXT    NOT NULL,
    prompt_template_id  TEXT    NOT NULL,
    processing_time_ms  INTEGER NOT NULL,
    token_count_input   INTEGER NOT NULL,
    token_count_output  INTEGER NOT NULL,
    flags               TEXT    NOT NULL,
    timestamp           TEXT    NOT NULL
);
"""

_INSERT = """
INSERT OR REPLACE INTO decisions
    (record_id, paper_id, stage, decision, confidence,
     inputs, outputs, model_used, model_version, prompt_template_id,
     processing_time_ms, token_count_input, token_count_output,
     flags, timestamp)
VALUES
    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""

_SELECT_BY_PAPER = "SELECT * FROM decisions WHERE paper_id = ? ORDER BY timestamp;"
_SELECT_BY_STAGE = "SELECT * FROM decisions WHERE stage = ?    ORDER BY timestamp;"
_SELECT_ALL      = "SELECT * FROM decisions ORDER BY timestamp;"


# ---------------------------------------------------------------------------
# DecisionLogger
# ---------------------------------------------------------------------------

class DecisionLogger:
    """
    Append-only audit log backed by SQLite.

    Parameters
    ----------
    review_id : str
        Used to name the database file: ``data/decisions_{review_id}.db``.
    db_path : Path, optional
        Override the default path (useful in tests).
    """

    def __init__(
        self,
        review_id: str,
        db_path: Optional[Path] = None,
    ) -> None:
        self._review_id = review_id
        if db_path is None:
            data_dir = Path("data")
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / f"decisions_{review_id}.db"

        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
        logger.info("DecisionLogger initialised at %s", self._db_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(self, record: DecisionRecord) -> None:
        """Persist one DecisionRecord.  Overwrites on duplicate record_id."""
        row = (
            record.record_id,
            record.paper_id,
            record.stage.value,
            record.decision.value,
            record.confidence,
            json.dumps(record.inputs,  default=str),
            json.dumps(record.outputs, default=str),
            record.model_used,
            record.model_version,
            record.prompt_template_id,
            record.processing_time_ms,
            record.token_count_input,
            record.token_count_output,
            json.dumps(record.flags),
            record.timestamp.isoformat(),
        )
        with self._lock:
            with self._connect() as conn:
                conn.execute(_INSERT, row)
        logger.debug("Logged decision %s for paper %s", record.record_id, record.paper_id)

    def get_by_paper(self, paper_id: str) -> List[DecisionRecord]:
        """Return all decisions for a single paper, oldest first."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(_SELECT_BY_PAPER, (paper_id,)).fetchall()
        return [_row_to_record(r) for r in rows]

    def get_by_stage(self, stage: Stage) -> List[DecisionRecord]:
        """Return all decisions recorded at a given pipeline stage."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(_SELECT_BY_STAGE, (stage.value,)).fetchall()
        return [_row_to_record(r) for r in rows]

    def export_json(self) -> str:
        """Serialise the entire decisions table to a JSON string."""
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(_SELECT_ALL).fetchall()
        records = [_row_to_dict(r) for r in rows]
        return json.dumps(records, indent=2, default=str)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn


# ---------------------------------------------------------------------------
# Row helpers (module-private)
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["inputs"]  = json.loads(d["inputs"])
    d["outputs"] = json.loads(d["outputs"])
    d["flags"]   = json.loads(d["flags"])
    return d


def _row_to_record(row: sqlite3.Row) -> DecisionRecord:
    from models.data_classes import Decision  # avoid any potential circular import

    d = dict(row)
    return DecisionRecord(
        record_id          = d["record_id"],
        paper_id           = d["paper_id"],
        stage              = Stage(d["stage"]),
        decision           = Decision(d["decision"]),
        confidence         = d["confidence"],
        inputs             = json.loads(d["inputs"]),
        outputs            = json.loads(d["outputs"]),
        model_used         = d["model_used"],
        model_version      = d["model_version"],
        prompt_template_id = d["prompt_template_id"],
        processing_time_ms = d["processing_time_ms"],
        token_count_input  = d["token_count_input"],
        token_count_output = d["token_count_output"],
        flags              = json.loads(d["flags"]),
        timestamp          = datetime.fromisoformat(d["timestamp"]),
    )
