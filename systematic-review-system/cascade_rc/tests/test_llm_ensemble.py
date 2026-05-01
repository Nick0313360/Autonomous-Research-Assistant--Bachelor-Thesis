"""
cascade_rc/tests/test_llm_ensemble.py
========================================
Tests for the refactored _majority_and_u (triple return) and edge-case voting logic.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from infrastructure.llm_client import LLMResponse


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
