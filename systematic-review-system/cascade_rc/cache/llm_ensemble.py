"""
cascade_rc/cache/llm_ensemble.py
===================================
B=5 stochastic ensemble over the Tier-2 abstract screening prompt.

Each call uses the existing abstract_screening.txt prompt with temperature=0.7
so individual predictions are stochastic.  Voting logic:

  - "Uncertain" votes are excluded from the Include / Exclude competition.
  - If Include > Exclude → majority = "Include",   u = include_count / B
  - If Exclude > Include → majority = "Exclude",   u = exclude_count / B
  - Tie (or all Uncertain) → majority = "Uncertain", u = 0.0  (hardcoded)

This ensures the self-consistency gate (τ_SE) fails for ambiguous abstracts,
routing them to the human-recovery branch (CASCADE-RC paper §4, eq. 2).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from infrastructure.llm_client import LLMClient
from tier2_screening.abstract_screener import _TEMPLATE, _fill_template

logger = logging.getLogger(__name__)

Vote = Literal["Include", "Exclude", "Uncertain"]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EnsembleResult:
    votes:    list[Vote]
    majority: Vote
    u:        float   # self-consistency score ∈ [0, 1]
    y_hat:    int     # 1 if majority == "Include" else 0


# ---------------------------------------------------------------------------
# Voting helpers
# ---------------------------------------------------------------------------

def _parse_vote(parsed_json: Any) -> Vote:
    """Map a parsed LLM JSON response to a vote label."""
    if not isinstance(parsed_json, dict):
        return "Uncertain"
    satisfies = parsed_json.get("satisfies", "uncertain")
    if satisfies is True or satisfies == "true":
        return "Include"
    if satisfies is False or satisfies == "false":
        return "Exclude"
    return "Uncertain"


def _vote_to_int(vote: Vote) -> int:
    """Map Vote label to integer: Include→1, Exclude→0, Uncertain→2."""
    if vote == "Include":
        return 1
    if vote == "Uncertain":
        return 2
    return 0


def _int_to_vote(v: int) -> Vote:
    """Map integer back to Vote label: 1→Include, 0→Exclude, 2→Uncertain."""
    if v == 1:
        return "Include"
    if v == 2:
        return "Uncertain"
    return "Exclude"


def _majority_and_u(votes: list[Vote], n: int) -> tuple[Vote, float, int]:
    """
    Compute majority label, self-consistency score u, and y_hat.

    Uncertain votes are excluded from the Include/Exclude binary competition.
    A tie (or all-Uncertain) resolves to majority='Uncertain', u=0.0, y_hat=0,
    which causes u < τ_SE and routes the abstract to human review.

    Returns (majority, u, y_hat).
    """
    include_count = votes.count("Include")
    exclude_count = votes.count("Exclude")

    if include_count > exclude_count:
        majority: Vote = "Include"
    elif exclude_count > include_count:
        majority = "Exclude"
    else:
        majority = "Uncertain"

    if majority == "Uncertain":
        return "Uncertain", 0.0, 0

    majority_count = include_count if majority == "Include" else exclude_count
    y_hat = 1 if majority == "Include" else 0
    return majority, majority_count / n, y_hat


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a precise systematic review screener. "
    "Reply only with the requested JSON."
)

_CRITERION_TEXT = (
    "The study satisfies all PICO eligibility criteria for this systematic review."
)


async def screen_abstract_ensemble(
    title: str,
    abstract: str,
    pico: dict,
    n_calls: int = 5,
    temperature: float = 0.7,
    _client: Optional[Any] = None,
) -> EnsembleResult:
    """
    Run B=n_calls stochastic screenings of one abstract and aggregate the votes.

    Parameters
    ----------
    title, abstract : str
        Paper metadata.
    pico : dict
        Keys: population, intervention, comparator, outcome, study_design.
    n_calls : int
        Ensemble size B (default 5).
    temperature : float
        LLM sampling temperature; must be > 0 for stochastic diversity.
    _client :
        Injected LLMClient (used in tests to avoid live API calls).

    Returns
    -------
    EnsembleResult with votes, majority, u ∈ [0, 1], y_hat ∈ {0, 1}.
    """
    client = _client if _client is not None else LLMClient()

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

    # Fire all B calls in parallel; BFH endpoint supports concurrent requests
    responses = await asyncio.gather(
        *[
            client.complete(
                prompt=prompt,
                system=_SYSTEM,
                model=client.GPT_MODEL,
                temperature=temperature,
                max_tokens=128,
                response_format="json",
            )
            for _ in range(n_calls)
        ]
    )

    votes: list[Vote] = [_parse_vote(r.parsed_json) for r in responses]
    majority, u, y_hat = _majority_and_u(votes, n_calls)

    logger.debug(
        "Ensemble: votes=%s majority=%s u=%.3f",
        votes, majority, u,
    )
    return EnsembleResult(votes=votes, majority=majority, u=u, y_hat=y_hat)
