from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cascade_rc.data.clef_tar_loader import load_topic

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
    with pytest.raises(FileNotFoundError, match=r"2019-TAR"):
        load_topic("CD008874", tmp_path)
