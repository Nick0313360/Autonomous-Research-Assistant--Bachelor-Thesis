"""
tier1_search/search_refinement.py
===================================
LLM-driven search query refinement.

Given a set of SearchQuery objects and a CoverageReport flagging gaps,
SearchRefinementAgent asks LLM-1 (gpt-oss:120b) to suggest additional
search terms and returns updated queries with those terms appended as
OR alternatives in domain_keywords.

Query versions are bumped: v1 → v2 → v3.  At iteration ≥ 3 the queries
are returned unchanged (hard cap to prevent runaway refinement).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from models.data_classes import ReviewProtocol, SearchQuery
from tier1_search.coverage_analyzer import CoverageReport

logger = logging.getLogger(__name__)

_MAX_ITERATION = 3

_SYSTEM_PROMPT = (
    "You are a systematic review search specialist. "
    "Given a set of identified coverage gaps in a literature search, "
    "suggest additional MeSH terms or free-text keywords that would help "
    "fill those gaps. "
    "Reply ONLY with a JSON object: "
    '{"new_terms": ["term1", "term2", ...]}. '
    "Suggest 3–8 terms. Do not include terms already in the existing keywords."
)


class SearchRefinementAgent:
    """
    Refines search queries by consulting an LLM about coverage gaps.
    """

    async def refine(
        self,
        queries:         List[SearchQuery],
        coverage_report: CoverageReport,
        protocol:        ReviewProtocol,
        llm_client:      Any,   # LLMClient — avoid circular imports
        iteration:       int,
    ) -> List[SearchQuery]:
        """
        Parameters
        ----------
        queries :
            Current list of SearchQuery objects.
        coverage_report :
            Output of CoverageAnalyzer.analyze().
        protocol :
            The review protocol (for PICO context).
        llm_client :
            Initialised LLMClient instance.
        iteration :
            Current refinement iteration (0-based).
            At iteration ≥ _MAX_ITERATION (3) queries are returned unchanged.

        Returns
        -------
        List[SearchQuery]
            Updated queries with new terms appended to domain_keywords.
            If no gaps exist or iteration is at the cap, the original list
            is returned unmodified.
        """
        if iteration >= _MAX_ITERATION:
            logger.info(
                "SearchRefinementAgent: iteration cap (%d) reached, returning unchanged",
                _MAX_ITERATION,
            )
            return queries

        if not coverage_report.has_gaps:
            logger.info("SearchRefinementAgent: no gaps detected, skipping refinement")
            return queries

        new_terms = await self._ask_llm(queries, coverage_report, protocol, llm_client)
        if not new_terms:
            logger.warning("SearchRefinementAgent: LLM returned no new terms")
            return queries

        updated = [
            self._bump_version(q, new_terms, iteration + 2)  # v2, v3, v4…
            for q in queries
        ]
        logger.info(
            "SearchRefinementAgent: added %d new terms at iteration %d → v%d",
            len(new_terms),
            iteration,
            iteration + 2,
        )
        return updated

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _ask_llm(
        self,
        queries:         List[SearchQuery],
        coverage_report: CoverageReport,
        protocol:        ReviewProtocol,
        llm_client:      Any,
    ) -> List[str]:
        existing_keywords = _collect_existing_keywords(queries)
        prompt = _build_prompt(coverage_report, protocol, existing_keywords)

        try:
            response = await llm_client.complete(
                prompt=prompt,
                system=_SYSTEM_PROMPT,
                model=llm_client.GPT_MODEL,
                temperature=0.3,
                max_tokens=256,
                response_format="json",
            )
        except Exception as exc:
            logger.error("SearchRefinementAgent: LLM call failed: %s", exc)
            return []

        return _parse_terms(response)

    @staticmethod
    def _bump_version(
        query: SearchQuery,
        new_terms: List[str],
        version_number: int,
    ) -> SearchQuery:
        """Return a new SearchQuery with new_terms merged into domain_keywords."""
        merged = list(query.domain_keywords)
        for t in new_terms:
            if t not in merged:
                merged.append(t)

        return query.model_copy(update={"domain_keywords": merged})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_existing_keywords(queries: List[SearchQuery]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for q in queries:
        for kw in q.domain_keywords:
            k = kw.strip().lower()
            if k and k not in seen:
                seen.add(k)
                result.append(kw)
    return result


def _build_prompt(
    report:   CoverageReport,
    protocol: ReviewProtocol,
    existing: List[str],
) -> str:
    pico = protocol.pico
    gaps_text = "\n".join(f"- {g}" for g in report.identified_gaps) or "None"
    kw_text   = ", ".join(existing[:30]) or "none"

    uncovered = [
        term for term, info in report.keyword_coverage.items()
        if not info["covered"]
    ]
    uncovered_text = ", ".join(uncovered) or "none"

    return (
        f"Systematic review: {protocol.research_question}\n\n"
        f"PICO:\n"
        f"  Population:    {pico.population}\n"
        f"  Intervention:  {pico.intervention}\n"
        f"  Comparator:    {pico.comparator}\n"
        f"  Outcome:       {pico.outcome}\n\n"
        f"Identified coverage gaps:\n{gaps_text}\n\n"
        f"PICO terms with < 5% coverage: {uncovered_text}\n\n"
        f"Current keywords (do NOT repeat these): {kw_text}\n\n"
        "Suggest additional search terms to address the gaps above."
    )


def _parse_terms(response: Any) -> List[str]:
    """Extract a list of strings from an LLMResponse."""
    # Try parsed_json first (set when response_format="json")
    parsed = getattr(response, "parsed_json", None)
    if isinstance(parsed, dict):
        terms = parsed.get("new_terms", [])
        if isinstance(terms, list):
            return [str(t).strip() for t in terms if str(t).strip()]

    # Fallback: regex extraction from raw content
    content = getattr(response, "content", "") or ""
    match = re.search(r'"new_terms"\s*:\s*\[([^\]]+)\]', content)
    if match:
        raw = match.group(1)
        return [
            t.strip().strip('"\'')
            for t in raw.split(",")
            if t.strip().strip('"\'')
        ]

    logger.warning("SearchRefinementAgent: could not parse terms from LLM response")
    return []
