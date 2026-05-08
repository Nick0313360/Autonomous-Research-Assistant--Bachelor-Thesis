"""Tests for no-abstract recovery and routing guard (Steps 4–5)."""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pandas as pd
import pytest

PARQUET_PATH = Path("artefacts/cascade_rc/data/CD008874.parquet")
SNAPSHOT_PATH = Path("artefacts/cascade_rc/data/CD008874_original_sha_snapshot.json")


def _load() -> pd.DataFrame:
    return pd.read_parquet(PARQUET_PATH)


# ---------------------------------------------------------------------------
# test_parquet_has_abstract_source_column
# ---------------------------------------------------------------------------

def test_parquet_has_abstract_source_column() -> None:
    df = _load()
    assert "abstract_source" in df.columns, "abstract_source column missing from parquet"
    assert df["abstract_source"].isna().sum() == 0, (
        f"abstract_source has {df['abstract_source'].isna().sum()} null values"
    )


# ---------------------------------------------------------------------------
# test_no_positive_has_empty_abstract_after_recovery
# ---------------------------------------------------------------------------

def test_no_positive_has_empty_abstract_after_recovery() -> None:
    df = _load()
    positives = df[df["y_abstract"] == 1].copy()
    for _, row in positives.iterrows():
        ab = str(row["abstract"]) if pd.notna(row["abstract"]) else ""
        src = row["abstract_source"]
        has_text = len(ab.strip()) > 0
        flagged = src == "unavailable"
        assert has_text or flagged, (
            f"PMID {row['pmid']}: silent empty-abstract positive — "
            f"abstract is empty but abstract_source={src!r} (expected 'unavailable')"
        )


# ---------------------------------------------------------------------------
# test_unavailable_positives_trigger_human_review_guard
# ---------------------------------------------------------------------------

def test_unavailable_positives_trigger_human_review_guard() -> None:
    from cascade_rc.integration.no_abstract_guard import (
        requires_human_review_due_to_no_abstract,
    )

    df = _load()
    unavailable_pos = df[(df["abstract_source"] == "unavailable") & (df["y_abstract"] == 1)]
    for _, row in unavailable_pos.iterrows():
        assert requires_human_review_due_to_no_abstract(row["abstract_source"]), (
            f"PMID {row['pmid']}: unavailable positive did not trigger human_review guard"
        )
    # If there are none, that's fine — the guard simply never fires in this run.


# ---------------------------------------------------------------------------
# test_original_rows_untouched
# ---------------------------------------------------------------------------

def test_original_rows_untouched() -> None:
    if not SNAPSHOT_PATH.exists():
        pytest.skip("SHA snapshot not found — run the recovery script first")

    snapshot: dict[str, str] = json.loads(SNAPSHOT_PATH.read_text())
    df = _load()
    original_rows = df[df["abstract_source"] == "original"]

    sample_size = min(20, len(original_rows))
    sample = original_rows.sample(n=sample_size, random_state=42)

    mismatches: list[str] = []
    for _, row in sample.iterrows():
        pmid = str(row["pmid"])
        if pmid not in snapshot:
            continue
        ab_val = str(row["abstract"]) if pd.notna(row["abstract"]) else ""
        current_sha = hashlib.sha256(ab_val.encode()).hexdigest()
        if current_sha != snapshot[pmid]:
            mismatches.append(pmid)

    assert len(mismatches) == 0, (
        f"{len(mismatches)} 'original' rows have changed abstract text: {mismatches}"
    )


# ---------------------------------------------------------------------------
# test_abstract_source_backward_compat
# ---------------------------------------------------------------------------

def test_abstract_source_backward_compat() -> None:
    from cascade_rc.integration.no_abstract_guard import get_abstract_source

    assert get_abstract_source({}) == "original"
    assert get_abstract_source({"abstract_source": "title_only"}) == "title_only"
    assert get_abstract_source({"abstract_source": "entrez_recovered"}) == "entrez_recovered"
    assert get_abstract_source({"abstract_source": "unavailable"}) == "unavailable"
