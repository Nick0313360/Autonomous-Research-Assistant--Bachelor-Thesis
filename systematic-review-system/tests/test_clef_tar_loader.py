from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PARQUET_DIR = _REPO_ROOT / "data" / "clef_tar"

from cascade_rc.data.clef_tar_loader import download_clef_tar_2019, fetch_abstracts, load_topic

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


def test_download_is_idempotent(tmp_path: Path) -> None:
    """If 2019-TAR already exists, download_clef_tar_2019 must be a no-op."""
    existing = tmp_path / "2019-TAR"
    existing.mkdir()
    sentinel = existing / "sentinel.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    download_clef_tar_2019(tmp_path)  # must not wipe or re-clone

    assert sentinel.exists(), "idempotent check failed — 2019-TAR was overwritten"


# ---------------------------------------------------------------------------
# Unit: fetch_abstracts
# ---------------------------------------------------------------------------

def test_fetch_abstracts_cache_hit(tmp_path: Path) -> None:
    """PMIDs already in abstracts.jsonl must not trigger a network call."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abstracts.jsonl").write_text(
        '{"pmid": "12345678", "title": "Test Title", "abstract": "Test abstract"}\n',
        encoding="utf-8",
    )

    result = fetch_abstracts(["12345678"], cache_dir)

    assert "12345678" in result
    assert result["12345678"]["title"] == "Test Title"
    assert result["12345678"]["abstract"] == "Test abstract"


def test_fetch_abstracts_missing_pmid_not_in_result(tmp_path: Path) -> None:
    """Empty PMID list returns empty dict — no network call."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "abstracts.jsonl").write_text("", encoding="utf-8")

    result = fetch_abstracts([], cache_dir)
    assert result == {}


def test_fetch_abstracts_creates_cache_dir(tmp_path: Path) -> None:
    """fetch_abstracts must create cache_dir if it does not exist."""
    cache_dir = tmp_path / "new_cache"
    fetch_abstracts([], cache_dir)
    assert cache_dir.exists()


# ---------------------------------------------------------------------------
# Integration: parquet output (skips if CLI has not been run yet)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("topic_id", ["CD008874", "CD012080", "CD012768"])
def test_minimum_positives(topic_id: str) -> None:
    path = _PARQUET_DIR / f"{topic_id}.parquet"
    if not path.exists():
        pytest.skip(f"{path} not yet generated — run the CLI first")
    df = pd.read_parquet(path)
    assert int(df["y_abstract"].sum()) >= 26, (
        f"{topic_id}: only {int(df['y_abstract'].sum())} positives, need ≥ 26"
    )


@pytest.mark.parametrize("topic_id", ["CD008874", "CD012080", "CD012768"])
def test_no_empty_title_or_abstract(topic_id: str) -> None:
    path = _PARQUET_DIR / f"{topic_id}.parquet"
    if not path.exists():
        pytest.skip(f"{path} not yet generated — run the CLI first")
    df = pd.read_parquet(path)
    assert (df["title"] != "").all(), f"{topic_id}: contains rows with empty title"
    assert (df["abstract"] != "").all(), f"{topic_id}: contains rows with empty abstract"


@pytest.mark.parametrize("topic_id", ["CD008874", "CD012080", "CD012768"])
def test_y_abstract_binary(topic_id: str) -> None:
    path = _PARQUET_DIR / f"{topic_id}.parquet"
    if not path.exists():
        pytest.skip(f"{path} not yet generated — run the CLI first")
    df = pd.read_parquet(path)
    assert set(df["y_abstract"].unique()).issubset({0, 1}), (
        f"{topic_id}: y_abstract contains values outside {{0, 1}}"
    )
