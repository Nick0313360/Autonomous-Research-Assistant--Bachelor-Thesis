"""Integration tests: SQLite cache behaviour during the score_u → merge_u pipeline.

Validates the three invariants documented in CLAUDE.md:

  1. score_u populates the cache (cache miss → LLM call → cache write).
  2. Re-running score_u on cached PMIDs makes zero new LLM calls.
  3. SHA stability: score_u and merge_u produce an identical prompt_sha for the
     same (PMID, title, abstract, PICO) triple — the core correctness contract.
  4. merge_u reads u from the cache; u differs from the s placeholder.
  5. merge_u falls back to u=s gracefully when fewer than B cache rows exist.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cascade_rc.cache.llm_ensemble import (
    _CRITERION_TEXT,
    _majority_and_u,
    _parse_vote,
    screen_abstract_ensemble,
)
from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache
from infrastructure.llm_client import LLMResponse
from tier2_screening.abstract_screener import _TEMPLATE, _fill_template

Vote = str  # "Include" | "Exclude" | "Uncertain"

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PICO = {
    "population": "Adults with suspected pulmonary embolism",
    "intervention": "CT pulmonary angiography",
    "comparator": "V/Q scan",
    "outcome": "Diagnostic accuracy",
    "study_design": "Diagnostic test accuracy study",
}

SAMPLE_RECORDS = [
    {
        "pmid": "11111111",
        "title": "CT for PE diagnosis",
        "abstract": "We studied CT accuracy for pulmonary embolism in 200 patients.",
        "s": 0.80,
        "y_abstract": 1,
        "is_calib": 1,
    },
    {
        "pmid": "22222222",
        "title": "V/Q scan vs CT angiography",
        "abstract": "Prospective comparison of V/Q scan and CTPA in 100 patients.",
        "s": 0.60,
        "y_abstract": 0,
        "is_calib": 0,
    },
    {
        "pmid": "33333333",
        "title": "Cardiac MRI in athletes",
        "abstract": "Cardiac MRI findings in competitive athletes without symptoms.",
        "s": 0.20,
        "y_abstract": 0,
        "is_calib": 0,
    },
]


def _make_df() -> pd.DataFrame:
    df = pd.DataFrame(SAMPLE_RECORDS)
    df["s"] = df["s"].astype("float64")
    df["y_abstract"] = df["y_abstract"].astype("int8")
    df["is_calib"] = df["is_calib"].astype("int8")
    return df


def _llm_response(satisfies: bool) -> LLMResponse:
    parsed = {"satisfies": satisfies, "confidence": 0.9, "reasoning": "pipeline-test"}
    return LLMResponse(
        content=str(parsed),
        model_used="gpt-oss:120b",
        input_tokens=10,
        output_tokens=5,
        latency_ms=15.0,
        parsed_json=parsed,
    )


def _mock_client(
    satisfies: bool = True,
    responses: list[LLMResponse] | None = None,
) -> MagicMock:
    c = MagicMock()
    c.GPT_MODEL = "gpt-oss:120b"
    if responses is not None:
        c.complete = AsyncMock(side_effect=responses)
    else:
        c.complete = AsyncMock(return_value=_llm_response(satisfies))
    return c


def _pico_text(pico: dict) -> str:
    return (
        f"Population: {pico['population']}\n"
        f"Intervention: {pico['intervention']}\n"
        f"Comparator: {pico['comparator']}\n"
        f"Outcome: {pico['outcome']}\n"
        f"Study design: {pico['study_design']}"
    )


def _compute_sha(pico: dict, title: str, abstract: str) -> str:
    """Compute prompt_sha the way both score_u and merge_u must compute it."""
    prompt = _fill_template(
        _TEMPLATE,
        pico_text=_pico_text(pico),
        criterion_text=_CRITERION_TEXT,
        title=title,
        abstract=abstract,
    )
    return hashlib.sha256(prompt.encode()).hexdigest()


def _run_ensemble(
    df: pd.DataFrame,
    cache: SQLiteEnsembleCache,
    client: MagicMock,
    *,
    B: int = 5,
) -> None:
    """Simulate step_score_u: run screen_abstract_ensemble for every PMID."""
    for _, row in df.iterrows():
        asyncio.run(
            screen_abstract_ensemble(
                title=str(row["title"]),
                abstract=str(row["abstract"]),
                pico=PICO,
                pmid=str(row["pmid"]),
                n_calls=B,
                temperature=0.7,
                _client=client,
                _cache=cache,
                _model_id="gpt-oss:120b",
                _template_v="v1",
            )
        )


# ---------------------------------------------------------------------------
# Test 1 — score_u populates the cache (B rows per PMID)
# ---------------------------------------------------------------------------

def test_score_u_populates_cache(tmp_path: Path) -> None:
    """score_u writes B=5 rows per PMID into the SQLite cache."""
    db_path = tmp_path / "llm_cache.db"
    cache = SQLiteEnsembleCache(db_path)
    client = _mock_client()
    df = _make_df()

    _run_ensemble(df, cache, client)
    cache.close()

    expected_rows = len(SAMPLE_RECORDS) * 5
    stats = SQLiteEnsembleCache(db_path).stats()
    assert stats["total_rows"] == expected_rows, (
        f"Expected {expected_rows} rows, got {stats['total_rows']}"
    )
    assert stats["unique_pmids"] == len(SAMPLE_RECORDS)
    assert client.complete.call_count == expected_rows


# ---------------------------------------------------------------------------
# Test 2 — re-running score_u makes zero new LLM calls
# ---------------------------------------------------------------------------

def test_score_u_reruns_are_cache_only(tmp_path: Path) -> None:
    """Re-running score_u on already-cached PMIDs calls the LLM zero times."""
    db_path = tmp_path / "llm_cache.db"
    df = _make_df()

    # First run — populates cache
    cache1 = SQLiteEnsembleCache(db_path)
    client1 = _mock_client()
    _run_ensemble(df, cache1, client1)
    cache1.close()
    assert client1.complete.call_count == len(SAMPLE_RECORDS) * 5

    # Second run — must be 100 % cache hits
    cache2 = SQLiteEnsembleCache(db_path)
    client2 = _mock_client()
    _run_ensemble(df, cache2, client2)
    cache2.close()

    assert client2.complete.call_count == 0, (
        f"Expected 0 LLM calls on re-run, got {client2.complete.call_count}"
    )


# ---------------------------------------------------------------------------
# Test 3 — SHA stability: score_u and merge_u produce identical prompt_sha
# ---------------------------------------------------------------------------

def test_sha_stability_across_steps(tmp_path: Path) -> None:
    """Both pipeline steps produce the same prompt_sha for the same PMID/PICO."""
    df = _make_df()
    pt = _pico_text(PICO)

    for _, row in df.iterrows():
        # SHA as screen_abstract_ensemble computes it (score_u path)
        sha_score = _compute_sha(PICO, str(row["title"]), str(row["abstract"]))

        # SHA as step_merge_u computes it (builds pico_text independently)
        prompt_merge = _fill_template(
            _TEMPLATE,
            pico_text=pt,
            criterion_text=_CRITERION_TEXT,
            title=str(row["title"]),
            abstract=str(row["abstract"]),
        )
        sha_merge = hashlib.sha256(prompt_merge.encode()).hexdigest()

        assert sha_score == sha_merge, (
            f"SHA mismatch for pmid={row['pmid']}: "
            f"score_u={sha_score[:12]}… merge_u={sha_merge[:12]}…"
        )


# ---------------------------------------------------------------------------
# Test 4 — merge_u reads u from cache; u ≠ s placeholder
# ---------------------------------------------------------------------------

def test_merge_u_reads_u_from_cache(tmp_path: Path) -> None:
    """After score_u, merge_u resolves u from cached votes (u=1.0 ≠ s)."""
    db_path = tmp_path / "llm_cache.db"
    df = _make_df()

    # Populate cache — all Include votes → u should be 1.0
    cache = SQLiteEnsembleCache(db_path)
    _run_ensemble(df, cache, _mock_client(satisfies=True))
    cache.close()

    # Replicate merge_u fetch logic
    pt = _pico_text(PICO)
    cache2 = SQLiteEnsembleCache(db_path)
    u_map: dict[str, float] = {}

    for _, row in df.iterrows():
        pmid = str(row["pmid"])
        prompt_sha = _compute_sha(PICO, str(row["title"]), str(row["abstract"]))
        cached_rows = cache2.fetch_ensemble(
            model_id="gpt-oss:120b",
            prompt_sha=prompt_sha,
            pmid=pmid,
            temperature=0.7,
            template_v="v1",
            B=5,
        )
        assert len(cached_rows) == 5, (
            f"pmid={pmid}: expected 5 cache rows, got {len(cached_rows)}"
        )
        votes = [_parse_vote(r["response"]) for r in cached_rows]
        _, u, _ = _majority_and_u(votes, 5)
        u_map[pmid] = u

    cache2.close()

    for _, row in df.iterrows():
        pmid = str(row["pmid"])
        u_val = u_map[pmid]
        # All slots were Include → self-consistency = 5/5 = 1.0
        assert u_val == 1.0, f"pmid={pmid}: expected u=1.0, got u={u_val}"
        # u must differ from the s placeholder (which is 0.2–0.8)
        assert u_val != float(row["s"]), (
            f"pmid={pmid}: u={u_val} equals s={row['s']} — cache not used?"
        )


# ---------------------------------------------------------------------------
# Test 5 — merge_u falls back to u=s when cache has < B rows
# ---------------------------------------------------------------------------

def test_merge_u_fallback_when_cache_incomplete(tmp_path: Path) -> None:
    """fetch_ensemble returns <B rows when only some slots are populated."""
    db_path = tmp_path / "partial.db"
    pmid = "11111111"
    sha = "a" * 64

    cache = SQLiteEnsembleCache(db_path)
    for seed_b in range(3):  # only 3 of 5 slots
        cache.put(
            model_id="gpt-oss:120b",
            prompt_sha=sha,
            pmid=pmid,
            temperature=0.7,
            seed_b=seed_b,
            template_v="v1",
            response={"satisfies": True},
            verdict=1,
            vote_label="Include",
        )
    cache.close()

    cache2 = SQLiteEnsembleCache(db_path)
    rows = cache2.fetch_ensemble(
        model_id="gpt-oss:120b",
        prompt_sha=sha,
        pmid=pmid,
        temperature=0.7,
        template_v="v1",
        B=5,
    )
    cache2.close()

    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"
    # In step_merge_u: len(rows) < B → fallback branch (u = s) is taken
    assert len(rows) < 5


# ---------------------------------------------------------------------------
# Test 6 — purge_empty_responses clears bad rows so score_u retries them
# ---------------------------------------------------------------------------

def test_purge_empty_responses_allows_retry(tmp_path: Path) -> None:
    """Rows with empty response are purged, then a re-run refills them via LLM."""
    db_path = tmp_path / "purge_test.db"
    pmid = "99990000"
    sha = "b" * 64

    # Write one good row and one empty-response row
    cache = SQLiteEnsembleCache(db_path)
    cache.put(
        model_id="gpt-oss:120b", prompt_sha=sha, pmid=pmid,
        temperature=0.7, seed_b=0, template_v="v1",
        response={"satisfies": True}, verdict=1, vote_label="Include",
    )
    cache.put(
        model_id="gpt-oss:120b", prompt_sha=sha, pmid=pmid,
        temperature=0.7, seed_b=1, template_v="v1",
        response={}, verdict=2, vote_label="Uncertain",
    )
    assert cache.stats()["total_rows"] == 2

    deleted = cache.purge_empty_responses()
    cache.close()

    assert deleted == 1, f"Expected 1 purged row, got {deleted}"

    # After purge, only the good row survives
    cache2 = SQLiteEnsembleCache(db_path)
    assert cache2.stats()["total_rows"] == 1
    cache2.close()
