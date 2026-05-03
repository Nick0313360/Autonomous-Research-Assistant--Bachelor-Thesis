"""
cascade_rc/tests/test_llm_ensemble.py
========================================
Tests for the refactored _majority_and_u (triple return) and edge-case voting logic.
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cascade_rc.cache.sqlite_cache import SQLiteEnsembleCache
from cascade_rc.cache.llm_ensemble import _CRITERION_TEXT
from infrastructure.llm_client import LLMResponse
from tier2_screening.abstract_screener import _TEMPLATE, _fill_template


_PICO = {
    "population": "patients with suspected knee injury",
    "intervention": "MRI",
    "comparator": "arthroscopy",
    "outcome": "diagnostic accuracy for meniscal tears",
    "study_design": "diagnostic test accuracy study",
}


def _resp(satisfies: bool | str) -> LLMResponse:
    parsed = {"satisfies": satisfies, "confidence": 0.9, "reasoning": "test"}
    return LLMResponse(
        content=str(parsed),
        model_used="gpt-oss:120b",
        input_tokens=20,
        output_tokens=10,
        latency_ms=50.0,
        parsed_json=parsed,
    )


def _mock_client(responses: list[LLMResponse]) -> MagicMock:
    client = MagicMock()
    client.GPT_MODEL = "gpt-oss:120b"
    client.complete = AsyncMock(side_effect=responses)
    return client


# ---------------------------------------------------------------------------
# Voting logic tests (no cache, no LLM)
# ---------------------------------------------------------------------------

def test_tie_uncertain_b5_2_2_1() -> None:
    """
    2 Include, 2 Exclude, 1 Uncertain → tie → majority='Uncertain', u=0.0, y_hat=0.

    Uncertain votes are excluded from the Include/Exclude binary competition, so
    Include=2 vs Exclude=2 is a tie. Tie resolves to Uncertain to force human review.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client(
        [_resp(True), _resp(True), _resp(False), _resp(False), _resp("uncertain")]
    )
    result = asyncio.run(
        screen_abstract_ensemble("T", "A", _PICO, n_calls=5, temperature=0.7, _client=client)
    )
    assert result.majority == "Uncertain"
    assert result.u == 0.0
    assert result.y_hat == 0


def test_tie_b4_genuine() -> None:
    """
    B=4, 2 Include, 2 Exclude → genuine tie → majority='Uncertain', u=0.0, y_hat=0.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client([_resp(True), _resp(True), _resp(False), _resp(False)])
    result = asyncio.run(
        screen_abstract_ensemble("T", "A", _PICO, n_calls=4, temperature=0.7, _client=client)
    )
    assert result.majority == "Uncertain"
    assert result.u == 0.0
    assert result.y_hat == 0


def test_b4_not_a_tie() -> None:
    """
    B=4, [Inc, Inc, Exc, Unc] is NOT a tie. Uncertain is excluded from competition:
    Include=2 vs Exclude=1 → Include wins. u = 2/4 = 0.5.

    This test explicitly prevents the regression of treating Uncertain as a tying vote.
    The original spec listed [Inc×2, Exc×1, Unc×1] as a B=4 tie — that is wrong.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client(
        [_resp(True), _resp(True), _resp(False), _resp("uncertain")]
    )
    result = asyncio.run(
        screen_abstract_ensemble("T", "A", _PICO, n_calls=4, temperature=0.7, _client=client)
    )
    assert result.majority == "Include"
    assert abs(result.u - 0.5) < 1e-9, f"Expected u=0.5, got {result.u}"
    assert result.y_hat == 1


def test_all_uncertain() -> None:
    """
    All 5 votes Uncertain (LLM completely unable to decide) → majority='Uncertain', u=0.0, y_hat=0.
    This is the pathological case that must always route to human review.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client([_resp("uncertain")] * 5)
    result = asyncio.run(
        screen_abstract_ensemble("T", "A", _PICO, n_calls=5, temperature=0.7, _client=client)
    )
    assert result.majority == "Uncertain"
    assert result.u == 0.0
    assert result.y_hat == 0
    assert result.votes.count("Uncertain") == 5


# ---------------------------------------------------------------------------
# Cache integration tests
# ---------------------------------------------------------------------------

def _make_prompt_sha(title: str, abstract: str, pico: dict) -> str:
    # mirrors screen_abstract_ensemble pico_text + _fill_template + sha256 block — update together
    pico_text = (
        f"Population: {pico.get('population', '')}\n"
        f"Intervention: {pico.get('intervention', '')}\n"
        f"Comparator: {pico.get('comparator', '')}\n"
        f"Outcome: {pico.get('outcome', '')}\n"
        f"Study design: {pico.get('study_design', '')}"
    )
    prompt = _fill_template(
        _TEMPLATE,
        pico_text=pico_text,
        criterion_text=_CRITERION_TEXT,
        title=title,
        abstract=str(abstract)[:500],
    )
    return hashlib.sha256(prompt.encode()).hexdigest()


def test_cache_hit_skips_llm(tmp_path: Path) -> None:
    """All 5 slots pre-populated: client.complete is never called."""
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    cache = SQLiteEnsembleCache(tmp_path / "test.db")
    title, abstract, pmid = "Test Title", "Test abstract.", "12345678"
    prompt_sha = _make_prompt_sha(title, abstract, _PICO)

    for seed_b in range(5):
        cache.put(
            model_id="gpt-oss:120b",
            prompt_sha=prompt_sha,
            pmid=pmid,
            temperature=0.7,
            seed_b=seed_b,
            template_v="v1",
            response={"satisfies": True},
            verdict=1,
            vote_label="Include",
        )

    client = MagicMock()
    client.GPT_MODEL = "gpt-oss:120b"
    client.complete = AsyncMock(side_effect=Exception("should not be called"))

    result = asyncio.run(
        screen_abstract_ensemble(
            title, abstract, _PICO,
            pmid=pmid, n_calls=5, temperature=0.7,
            _client=client, _cache=cache, _template_v="v1",
        )
    )
    assert client.complete.call_count == 0
    assert len(result.votes) == 5
    assert result.majority == "Include"
    cache.close()


def test_partial_cache_completion(tmp_path: Path) -> None:
    """
    Slots 0, 2, 4 pre-populated: only slots 1 and 3 trigger LLM calls.
    Order is preserved: cached slot 0 appears at index 0, not appended last.
    This is the within-PMID resumability test (crash mid-ensemble scenario).
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    cache = SQLiteEnsembleCache(tmp_path / "test.db")
    title, abstract, pmid = "Partial Title", "Partial abstract.", "88888888"
    prompt_sha = _make_prompt_sha(title, abstract, _PICO)

    for seed_b in [0, 2, 4]:
        cache.put(
            model_id="gpt-oss:120b",
            prompt_sha=prompt_sha,
            pmid=pmid,
            temperature=0.7,
            seed_b=seed_b,
            template_v="v1",
            response={"satisfies": True},
            verdict=1,
            vote_label="Include",
        )

    client = _mock_client([_resp(True), _resp(True)])  # for slots 1 and 3

    result = asyncio.run(
        screen_abstract_ensemble(
            title, abstract, _PICO,
            pmid=pmid, n_calls=5, temperature=0.7,
            _client=client, _cache=cache, _template_v="v1",
        )
    )

    assert client.complete.call_count == 2, f"Expected 2 LLM calls, got {client.complete.call_count}"
    assert len(result.votes) == 5
    # Cached slots at indices 0, 2, 4 are Include; LLM slots 1, 3 also Include here
    assert result.votes[0] == "Include"  # cached
    assert result.votes[1] == "Include"  # LLM
    assert result.votes[2] == "Include"  # cached
    assert result.votes[3] == "Include"  # LLM
    assert result.votes[4] == "Include"  # cached
    cache.close()
