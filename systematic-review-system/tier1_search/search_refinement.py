"""
tier1_search/search_refinement.py
===================================
LLM-driven search query refinement with three operating modes.

Mode selection (based on coverage_report.total_records):

  RELAX      < _LOW_RESULT_THRESHOLD (20)
      The current query is over-specified.  The LLM is instructed to drop
      Comparator and Outcome blocks, keeping only Population + Intervention,
      and to remove all exact-phrase quoting.

  FILL_GAPS  20 – 5000 results, coverage gaps exist
      Normal operation.  The LLM adds OR synonyms for uncovered PICO terms
      inside the existing concept blocks.

  NARROW     > _HIGH_RESULT_THRESHOLD (5000)
      Too many results.  The LLM adds 1–2 AND constraints built from the
      most discriminating remaining PICO terms.

All modes produce a fresh (pubmed_query, semantic_scholar_query) pair that
is written into SearchQuery.pubmed_query_override / .s2_query_override so
the connectors use the new strings directly on the next iteration.

Query versions are bumped: v1 → v2 → v3.  At iteration ≥ 3 the queries are
returned unchanged (hard cap to prevent runaway refinement).
"""
from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import Any, List, Optional, Tuple

from models.data_classes import ReviewProtocol, SearchQuery
from tier1_search.coverage_analyzer import CoverageReport

logger = logging.getLogger(__name__)

_MAX_ITERATION        = 3
_LOW_RESULT_THRESHOLD  = 20    # below → RELAX
_HIGH_RESULT_THRESHOLD = 5000  # above → NARROW


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------

class _RefineMode(Enum):
    RELAX     = "relax"
    FILL_GAPS = "fill_gaps"
    NARROW    = "narrow"


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_RELAX_SYSTEM_PROMPT = """\
You are a systematic review search specialist. The last database search returned CRITICALLY FEW
results — the query is over-specified and must be BROADENED.

RELAXATION RULES (all mandatory):
1. Retain ONLY the Intervention concept block — it is the most essential element.
2. COMPLETELY REMOVE the Comparator block.
3. COMPLETELY REMOVE the Outcome block, OR replace it with at most the 2 most generic terms.
4. Remove ALL quotation marks from individual terms — bare unquoted keywords enable
   fuzzy/partial matching that quoted phrases suppress.
5. Use OR to combine the core intervention synonyms.
6. PubMed: use bare keywords or very short (≤ 2-word) terms with [TIAB], joined by OR.
7. Semantic Scholar: output ONLY 2–3 individual keywords; no quotes, no Boolean operators.

Return ONLY this JSON object (no markdown, no explanation):
{"pubmed_query": "...", "semantic_scholar_query": "..."}
"""

_FILL_GAPS_SYSTEM_PROMPT = """\
You are a systematic review search specialist. A literature search returned results but has
keyword coverage gaps — certain PICO terms appear in fewer than 5 % of retrieved records.
Generate an UPDATED query that adds OR synonyms to fill the gaps.

RULES:
1. Keep the existing core AND structure — do NOT remove existing concept blocks.
2. Add OR synonyms inside existing blocks for each uncovered term.
3. Rule of 3: NEVER wrap phrases longer than 3 words in quotation marks.
4. PubMed: apply [TIAB] to every term.
5. Semantic Scholar: 3–5 individual keywords; no quotes, no Boolean operators.

Return ONLY this JSON object (no markdown, no explanation):
{"pubmed_query": "...", "semantic_scholar_query": "..."}
"""

_NARROW_SYSTEM_PROMPT = """\
You are a systematic review search specialist. The last search returned TOO MANY results.
Generate an UPDATED query that adds 1–2 additional AND constraints to narrow the results.

RULES:
1. Keep all existing concept blocks.
2. Add 1–2 new AND blocks using the most discriminating PICO terms not yet in the query.
3. Rule of 3: NEVER wrap phrases longer than 3 words in quotation marks.
4. PubMed: apply [TIAB] to every term.
5. Semantic Scholar: add 1–2 more specific keywords; no quotes, no Boolean operators.

Return ONLY this JSON object (no markdown, no explanation):
{"pubmed_query": "...", "semantic_scholar_query": "..."}
"""

_MODE_SYSTEM: dict[_RefineMode, str] = {
    _RefineMode.RELAX:     _RELAX_SYSTEM_PROMPT,
    _RefineMode.FILL_GAPS: _FILL_GAPS_SYSTEM_PROMPT,
    _RefineMode.NARROW:    _NARROW_SYSTEM_PROMPT,
}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SearchRefinementAgent:
    """
    Refines search queries by consulting an LLM about coverage gaps or result-count issues.
    """

    async def refine(
        self,
        queries:         List[SearchQuery],
        coverage_report: CoverageReport,
        protocol:        ReviewProtocol,
        llm_client:      Any,
        iteration:       int,
    ) -> List[SearchQuery]:
        """
        Parameters
        ----------
        queries :
            Current list of SearchQuery objects.
        coverage_report :
            Output of CoverageAnalyzer.analyze() — must carry total_records.
        protocol :
            The review protocol (for PICO context).
        llm_client :
            Initialised LLMClient instance.
        iteration :
            Current refinement iteration (0-based).

        Returns
        -------
        List[SearchQuery]
            Updated queries with new pubmed_query_override / s2_query_override.
            Returns the originals unchanged when the iteration cap is reached or
            the LLM call fails.
        """
        if iteration >= _MAX_ITERATION:
            logger.info(
                "SearchRefinementAgent: iteration cap (%d) reached, returning unchanged",
                _MAX_ITERATION,
            )
            return queries

        mode = _determine_mode(coverage_report)
        if mode is None:
            logger.info("SearchRefinementAgent: no refinement needed (no gaps, adequate results)")
            return queries

        logger.info(
            "SearchRefinementAgent: mode=%s  total_records=%d  iteration=%d",
            mode.value, coverage_report.total_records, iteration,
        )

        result = await self._ask_llm(queries, coverage_report, protocol, llm_client, mode)
        if result is None:
            logger.warning("SearchRefinementAgent: LLM returned no usable query — returning unchanged")
            return queries

        pubmed_q, s2_q = result
        updated = [_apply_refined_query(q, pubmed_q, s2_q) for q in queries]
        logger.info(
            "SearchRefinementAgent: %s → pubmed='%s'  s2='%s'",
            mode.value, pubmed_q[:120], s2_q[:80],
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
        mode:            _RefineMode,
    ) -> Optional[Tuple[str, str]]:
        prompt = _build_prompt(queries, coverage_report, protocol, mode)
        system = _MODE_SYSTEM[mode]

        try:
            response = await llm_client.complete(
                prompt          = prompt,
                system          = system,
                model           = llm_client.GPT_MODEL,
                temperature     = 0.3,
                max_tokens      = 512,
                response_format = "json",
            )
        except Exception as exc:
            logger.error("SearchRefinementAgent: LLM call failed: %s", exc)
            return None

        return _parse_query_pair(response)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _determine_mode(report: CoverageReport) -> Optional[_RefineMode]:
    """Return the appropriate refinement mode, or None if no action needed."""
    n = report.total_records
    if n < _LOW_RESULT_THRESHOLD:
        return _RefineMode.RELAX
    if n > _HIGH_RESULT_THRESHOLD:
        return _RefineMode.NARROW
    if report.has_gaps:
        return _RefineMode.FILL_GAPS
    return None


def _build_prompt(
    queries:  List[SearchQuery],
    report:   CoverageReport,
    protocol: ReviewProtocol,
    mode:     _RefineMode,
) -> str:
    pico = protocol.pico
    n = report.total_records

    # Current query strings for LLM context
    current_pm = _current_pubmed_str(queries)
    current_s2 = _current_s2_str(queries)

    header = {
        _RefineMode.RELAX:     f"The last search returned only {n} result(s) — CRITICALLY BELOW the minimum threshold of {_LOW_RESULT_THRESHOLD}.",
        _RefineMode.FILL_GAPS: f"The last search returned {n} results but has keyword coverage gaps.",
        _RefineMode.NARROW:    f"The last search returned {n} results — ABOVE the manageable threshold of {_HIGH_RESULT_THRESHOLD}.",
    }[mode]

    lines = [
        header,
        "",
        f"Research question: {protocol.research_question}",
        "",
        "PICO:",
        f"  Population:   {pico.population}",
        f"  Intervention: {pico.intervention}",
        f"  Comparator:   {pico.comparator}",
        f"  Outcome:      {pico.outcome}",
        "",
        "Current queries:",
        f"  PubMed: {current_pm}",
        f"  S2:     {current_s2}",
    ]

    if mode == _RefineMode.FILL_GAPS:
        gaps_text = "\n".join(f"  - {g}" for g in report.identified_gaps) or "  None"
        uncovered = [
            term for term, info in report.keyword_coverage.items()
            if not info["covered"]
        ]
        lines += [
            "",
            "Coverage gaps:",
            gaps_text,
            "",
            f"Uncovered PICO terms (< 5 % of records): {', '.join(uncovered) or 'none'}",
        ]

    return "\n".join(lines)


def _current_pubmed_str(queries: List[SearchQuery]) -> str:
    if not queries:
        return "(none)"
    q = queries[0]
    if q.pubmed_query_override:
        return q.pubmed_query_override
    return ", ".join(q.domain_keywords[:10]) or "(no keywords)"


def _current_s2_str(queries: List[SearchQuery]) -> str:
    if not queries:
        return "(none)"
    q = queries[0]
    if q.s2_query_override:
        return q.s2_query_override
    return ", ".join(q.domain_keywords[:5]) or "(no keywords)"


def _apply_refined_query(
    query: SearchQuery,
    pubmed_q: str,
    s2_q: str,
) -> SearchQuery:
    return query.model_copy(update={
        "pubmed_query_override": pubmed_q,
        "s2_query_override":     s2_q,
    })


def _parse_query_pair(response: Any) -> Optional[Tuple[str, str]]:
    """
    Extract (pubmed_query, s2_query) from an LLMResponse.
    Returns None if parsing fails.
    """
    parsed = getattr(response, "parsed_json", None)
    if isinstance(parsed, dict):
        pm = parsed.get("pubmed_query", "").strip()
        s2 = parsed.get("semantic_scholar_query", "").strip()
        if pm and s2:
            return pm, s2

    content = getattr(response, "content", "") or ""
    content = re.sub(r"```(?:json)?\s*", "", content).strip()
    try:
        obj = json.loads(content)
        pm = obj.get("pubmed_query", "").strip()
        s2 = obj.get("semantic_scholar_query", "").strip()
        if pm and s2:
            return pm, s2
    except (json.JSONDecodeError, AttributeError):
        pass

    pm_match = re.search(r'"pubmed_query"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    s2_match = re.search(r'"semantic_scholar_query"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    if pm_match and s2_match:
        return pm_match.group(1).strip(), s2_match.group(1).strip()

    logger.warning("SearchRefinementAgent: could not parse query pair from LLM response")
    return None
