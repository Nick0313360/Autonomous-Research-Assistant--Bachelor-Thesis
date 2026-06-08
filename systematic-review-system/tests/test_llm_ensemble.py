"""
tests/test_llm_ensemble.py
============================
TDD: written *before* cascade_rc/cache/llm_ensemble.py.

Four required cases (spec §5)
------------------------------
(a) all 5 "Include"                      → majority="Include",   u=1.0,  y_hat=1
(b) 3 "Include", 2 "Exclude"             → majority="Include",   u=0.6,  y_hat=1
(c) 2 "Include", 2 "Exclude", 1 "Uncertain" → majority="Uncertain", u=0.0, y_hat=0
(d) 3 "Uncertain" + 1 "Include" + 1 "Exclude"  (1:1 tie) → majority="Uncertain", u=0.0

No live LLM is called; the client is replaced with an AsyncMock in every test.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from infrastructure.llm_client import LLMResponse


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _resp(satisfies: bool | str) -> LLMResponse:
    """Build a scripted LLMResponse for a given 'satisfies' value."""
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
    """Return a mock LLMClient whose complete() returns responses in order."""
    client = MagicMock()
    client.GPT_MODEL = "gpt-oss:120b"
    client.complete = AsyncMock(side_effect=responses)
    return client


_PICO = {
    "population": "patients with suspected knee injury",
    "intervention": "MRI",
    "comparator": "arthroscopy",
    "outcome": "diagnostic accuracy for meniscal tears",
    "study_design": "diagnostic test accuracy study",
}


# ---------------------------------------------------------------------------
# (a) All 5 "Include"
# ---------------------------------------------------------------------------

def test_all_include_votes() -> None:
    """5/5 Include → majority='Include', u=1.0, y_hat=1."""
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client([_resp(True)] * 5)
    result = asyncio.run(
        screen_abstract_ensemble(
            "Test Title", "Test abstract.", _PICO,
            n_calls=5, temperature=0.7, _client=client,
        )
    )

    assert result.votes.count("Include") == 5
    assert result.votes.count("Exclude") == 0
    assert result.majority == "Include"
    assert result.u == 1.0
    assert result.y_hat == 1


# ---------------------------------------------------------------------------
# (b) 3 Include, 2 Exclude
# ---------------------------------------------------------------------------

def test_three_include_two_exclude() -> None:
    """3 Include, 2 Exclude → majority='Include', u=0.6, y_hat=1."""
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client(
        [_resp(True), _resp(True), _resp(True), _resp(False), _resp(False)]
    )
    result = asyncio.run(
        screen_abstract_ensemble(
            "Test Title", "Test abstract.", _PICO,
            n_calls=5, temperature=0.7, _client=client,
        )
    )

    assert result.votes.count("Include") == 3
    assert result.votes.count("Exclude") == 2
    assert result.majority == "Include"
    assert abs(result.u - 0.6) < 1e-9, f"Expected u=0.6, got {result.u}"
    assert result.y_hat == 1


# ---------------------------------------------------------------------------
# (c) 2 Include, 2 Exclude, 1 Uncertain → tie → Uncertain
# ---------------------------------------------------------------------------

def test_two_include_two_exclude_one_uncertain_breaks_to_uncertain() -> None:
    """Include=2, Exclude=2, Uncertain=1 → tie → majority='Uncertain', u=0.0."""
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client(
        [_resp(True), _resp(True), _resp(False), _resp(False), _resp("uncertain")]
    )
    result = asyncio.run(
        screen_abstract_ensemble(
            "Test Title", "Test abstract.", _PICO,
            n_calls=5, temperature=0.7, _client=client,
        )
    )

    assert result.votes.count("Include") == 2
    assert result.votes.count("Exclude") == 2
    assert result.votes.count("Uncertain") == 1
    assert result.majority == "Uncertain"
    assert result.u == 0.0
    assert result.y_hat == 0


# ---------------------------------------------------------------------------
# (d) 3 Uncertain + 1 Include + 1 Exclude → tie → Uncertain, u=0.0
# ---------------------------------------------------------------------------

def test_uncertain_plurality_with_tied_non_uncertain_votes() -> None:
    """
    3 Uncertain + 1 Include + 1 Exclude: Uncertain votes are excluded from the
    Include/Exclude competition; the 1:1 tie breaks toward majority='Uncertain', u=0.0.
    """
    from cascade_rc.cache.llm_ensemble import screen_abstract_ensemble

    client = _mock_client(
        [
            _resp("uncertain"),
            _resp("uncertain"),
            _resp("uncertain"),
            _resp(True),
            _resp(False),
        ]
    )
    result = asyncio.run(
        screen_abstract_ensemble(
            "Test Title", "Test abstract.", _PICO,
            n_calls=5, temperature=0.7, _client=client,
        )
    )

    assert result.votes.count("Uncertain") == 3
    assert result.votes.count("Include") == 1
    assert result.votes.count("Exclude") == 1
    assert result.majority == "Uncertain"
    assert result.u == 0.0
    assert result.y_hat == 0


# ---------------------------------------------------------------------------
# Extra: EnsembleResult dataclass contract
# ---------------------------------------------------------------------------

def test_ensemble_result_has_required_fields() -> None:
    """EnsembleResult must expose votes, majority, u, y_hat."""
    from cascade_rc.cache.llm_ensemble import EnsembleResult

    er = EnsembleResult(
        votes=["Include", "Include"],
        majority="Include",
        u=1.0,
        y_hat=1,
    )
    assert hasattr(er, "votes")
    assert hasattr(er, "majority")
    assert hasattr(er, "u")
    assert hasattr(er, "y_hat")
