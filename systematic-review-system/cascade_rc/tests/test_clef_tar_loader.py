"""Tests for Prompt 1.1: qrel validation, dedup audit, m₊ recomputation, split reproducibility."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from cascade_rc.data.clef_tar_loader import (
    _parse_qrels_trec,
    detect_topic_duplications,
    load_topic,
)
from cascade_rc.data.splits import stratified_calib_test_split


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_qrel_lines(path: Path, entries: list[tuple[str, str, int]]) -> None:
    """Write TREC-format qrel lines: topic_id 0 pmid rel."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{t} 0 {p} {r}\n" for t, p, r in entries),
        encoding="utf-8",
    )


def _make_dta_data_dir(tmp_path: Path, topic_id: str, qrels: dict[str, int]) -> Path:
    """Build a minimal 2019-TAR DTA Testing tree for unit tests."""
    dta = tmp_path / "2019-TAR" / "Task2" / "Testing" / "DTA"
    (dta / "topics").mkdir(parents=True)
    (dta / "qrels").mkdir(parents=True)
    pids_block = "".join(f"    {p} \n" for p in qrels)
    (dta / "topics" / topic_id).write_text(
        f"Topic: {topic_id}\nTitle: Fake topic\nQuery:\nsome query\nPids:\n{pids_block}",
        encoding="utf-8",
    )
    (dta / "qrels" / "qrel_abs_test.txt").write_text(
        "".join(f"{topic_id} 0 {p} {r}\n" for p, r in qrels.items()),
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# test_qrels_format_trec_compliant
# ---------------------------------------------------------------------------

def test_qrels_format_trec_compliant(tmp_path: Path) -> None:
    """Every parsed qrel line has 4 whitespace-separated fields; relevance ∈ {0, 1}."""
    p = tmp_path / "qrel_abs_test.txt"
    p.write_text(
        "CD008874 0 11111111 1\n"
        "CD008874 0 22222222 0\n"
        "CD012080 0 33333333 1\n",
        encoding="utf-8",
    )
    records = _parse_qrels_trec(p)
    assert len(records) == 3
    for _topic, _iter_val, _pmid, rel in records:
        assert rel in {0, 1}, f"relevance {rel!r} outside {{0, 1}}"


def test_qrels_trec_rejects_bad_relevance(tmp_path: Path) -> None:
    """_parse_qrels_trec raises ValueError when a relevance value ∉ {0, 1}."""
    p = tmp_path / "bad.txt"
    p.write_text("CD008874 0 99999999 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="relevance"):
        _parse_qrels_trec(p)


# ---------------------------------------------------------------------------
# test_topic_dedup_2019_minus_2018
# ---------------------------------------------------------------------------

def test_topic_dedup_2019_minus_2018(tmp_path: Path) -> None:
    """2019 DTA training topics == union of 2018 DTA train + test; duplicates flagged."""
    # 2018 training: CD000001, CD000002
    _write_qrel_lines(
        tmp_path / "2018-TAR" / "Task2" / "Training" / "DTA" / "qrels" / "train.qrels",
        [("CD000001", "10000001", 1), ("CD000002", "10000002", 0)],
    )
    # 2018 test: CD000003
    _write_qrel_lines(
        tmp_path / "2018-TAR" / "Task2" / "Testing" / "DTA" / "qrels" / "qrel_abs_test.txt",
        [("CD000003", "10000003", 1)],
    )
    # 2019 training: exactly 2018_train ∪ 2018_test
    _write_qrel_lines(
        tmp_path / "2019-TAR" / "Task2" / "Training" / "DTA" / "qrels" / "qrel_abs_train.txt",
        [
            ("CD000001", "10000001", 1),
            ("CD000002", "10000002", 0),
            ("CD000003", "10000003", 1),
        ],
    )
    audit_path = tmp_path / "topic_audit.json"
    detect_topic_duplications(tmp_path, families=["DTA"], audit_path=audit_path)

    loaded = json.loads(audit_path.read_text(encoding="utf-8"))
    assert loaded["dta_2019_train_equals_2018_union"] is True
    for tid in ("CD000001", "CD000002", "CD000003"):
        assert tid in loaded["duplicates"]["DTA"], f"{tid} not flagged as duplicate"


# ---------------------------------------------------------------------------
# test_m_plus_recomputed
# ---------------------------------------------------------------------------

def test_m_plus_recomputed(tmp_path: Path) -> None:
    """m₊ derived from qrels equals the known number of relevant abstracts."""
    n_pos, n_neg = 30, 70
    qrels = {str(i).zfill(8): (1 if i <= n_pos else 0) for i in range(1, n_pos + n_neg + 1)}
    data_dir = _make_dta_data_dir(tmp_path, "CD008874", qrels)

    topic = load_topic("CD008874", data_dir, family="DTA")
    m_plus = sum(v for v in topic.qrels_abstract.values() if v == 1)

    assert m_plus == n_pos, f"m₊={m_plus} != expected {n_pos}"


# ---------------------------------------------------------------------------
# test_split_seed_reproducible
# ---------------------------------------------------------------------------

def test_split_seed_reproducible(tmp_path: Path) -> None:
    """Running stratified_calib_test_split twice with the same seed produces byte-identical parquets."""
    df = pd.DataFrame({
        "pmid": [str(i) for i in range(100)],
        "title": ["t"] * 100,
        "abstract": ["a"] * 100,
        "y_abstract": pd.array([1, 0] * 50, dtype="int8"),
    })
    out1 = tmp_path / "split1.parquet"
    out2 = tmp_path / "split2.parquet"

    stratified_calib_test_split(
        df, calib_frac=0.5, fallback_8020_when_m_plus_at_least=200, seed=42, out_path=out1
    )
    stratified_calib_test_split(
        df, calib_frac=0.5, fallback_8020_when_m_plus_at_least=200, seed=42, out_path=out2
    )

    assert out1.read_bytes() == out2.read_bytes(), "Split parquets differ across identical runs"
