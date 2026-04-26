"""CLEF-TAR 2019 benchmark ingestion for CASCADE-RC validation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
