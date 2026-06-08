"""
tests/test_query_generation.py
================================
Validation tests for the Phase 1 query-generation pipeline.

Exercises the exact PICO intervention string that caused the original
zero-result failure:
  "implementation of a sugar-sweetened beverage (SSB) tax,
   soda tax, or sugary drink excise tax"

Test structure
--------------
1. _tiab_term()          — Rule-of-3 enforcement on individual phrases
2. _build_pubmed_query() — Full PubMed query format from rule-based path
3. _build_s2_query()     — Semantic Scholar query format from rule-based path
4. LLMQueryBuilder       — Override plumbing (mocked LLM, no live API call)
5. _determine_mode()     — Refinement mode selection by result count
6. SearchRefinementAgent — Full refinement flow (mocked LLM)

No live LLM is called; all LLM interactions use AsyncMock / MagicMock.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from infrastructure.llm_client import LLMResponse
from models.data_classes import PICO, CandidateRecord, ReviewProtocol, SearchQuery
from tier1_search.coverage_analyzer import CoverageAnalyzer, CoverageReport
from tier1_search.pubmed_connector import _build_pubmed_query, _tiab_term
from tier1_search.query_builder import LLMQueryBuilder, QueryBuilder, _extract_phrases
from tier1_search.search_refinement import (
    SearchRefinementAgent,
    _RefineMode,
    _determine_mode,
)
from tier1_search.semantic_scholar_connector import _build_s2_query

# ---------------------------------------------------------------------------
# Shared PICO fixture — the failing intervention string
# ---------------------------------------------------------------------------

SSB_INTERVENTION = (
    "implementation of a sugar-sweetened beverage (SSB) tax, "
    "soda tax, or sugary drink excise tax"
)


def _ssb_protocol() -> ReviewProtocol:
    return ReviewProtocol(
        title="SSB Tax Review",
        research_question="Does a sugar-sweetened beverage tax reduce obesity rates?",
        pico=PICO(
            population="general population including children and adults",
            intervention=SSB_INTERVENTION,
            comparator="jurisdictions without an SSB tax",
            outcome="obesity rates body weight BMI overweight prevalence",
            study_design="observational cohort or quasi-experimental",
        ),
        inclusion_criteria=[],
        exclusion_criteria=[],
        target_databases=["pubmed", "semantic_scholar"],
    )


def _ssb_query() -> SearchQuery:
    return QueryBuilder().build_initial_queries(_ssb_protocol())[0]


# ---------------------------------------------------------------------------
# Shared assertion helper
# ---------------------------------------------------------------------------

def _assert_no_long_quoted_phrases(query_str: str) -> None:
    """
    Fail if any double-quoted substring in *query_str* contains more than 3 words.
    This enforces the 'Rule of 3' that prevents zero-result PubMed searches.
    """
    for phrase in re.findall(r'"([^"]+)"', query_str):
        word_count = len(phrase.split())
        assert word_count <= 3, (
            f'Quoted phrase with {word_count} words violates Rule of 3: "{phrase}"\n'
            f"Full query: {query_str}"
        )


def _assert_no_boolean_operators(query_str: str) -> None:
    """Fail if the query contains PubMed/Boolean operators or TIAB tags."""
    for operator in (" AND ", " OR ", " NOT ", "[TIAB]", "[MeSH]"):
        assert operator not in query_str, (
            f"S2 query must not contain boolean operators; found {operator!r}\n"
            f"Full query: {query_str}"
        )


def _assert_no_quotes(query_str: str) -> None:
    """Fail if the query string contains double-quoted substrings."""
    assert '"' not in query_str, (
        f"S2 query must not contain double quotes.\nFull query: {query_str}"
    )


# ---------------------------------------------------------------------------
# Mock LLM helpers
# ---------------------------------------------------------------------------

def _llm_response(payload: dict) -> LLMResponse:
    """Build a scripted LLMResponse carrying *payload* as parsed_json."""
    return LLMResponse(
        content=str(payload),
        model_used="gpt-oss:120b",
        input_tokens=30,
        output_tokens=40,
        latency_ms=100.0,
        parsed_json=payload,
    )


def _mock_llm(response: LLMResponse) -> MagicMock:
    """Return a mock LLMClient that returns *response* on every complete() call."""
    client = MagicMock()
    client.GPT_MODEL = "gpt-oss:120b"
    client.complete = AsyncMock(return_value=response)
    return client


def _failing_llm() -> MagicMock:
    """Return a mock LLMClient whose complete() always raises RuntimeError."""
    client = MagicMock()
    client.GPT_MODEL = "gpt-oss:120b"
    client.complete = AsyncMock(side_effect=RuntimeError("simulated LLM failure"))
    return client


# ---------------------------------------------------------------------------
# 1. _tiab_term — Rule-of-3 enforcement
# ---------------------------------------------------------------------------

class TestTiabTerm:
    def test_single_word_is_quoted(self) -> None:
        assert _tiab_term("obesity") == '"obesity"[TIAB]'

    def test_two_word_phrase_is_quoted(self) -> None:
        assert _tiab_term("soda tax") == '"soda tax"[TIAB]'

    def test_three_word_phrase_is_quoted(self) -> None:
        assert _tiab_term("sugar sweetened beverage") == '"sugar sweetened beverage"[TIAB]'

    def test_four_word_phrase_is_NOT_quoted(self) -> None:
        result = _tiab_term("sugary drink excise tax")
        # Must not wrap the whole phrase in quotes
        assert '"sugary drink excise tax"' not in result
        # Each content word should appear with [TIAB]
        assert "sugary[TIAB]" in result
        assert "excise[TIAB]" in result
        assert "tax[TIAB]" in result

    def test_long_phrase_drops_stopwords(self) -> None:
        # "of" and "a" are stopwords — they must not appear as standalone TIAB terms
        result = _tiab_term("implementation of a sugar-sweetened beverage SSB tax")
        assert '"of"[TIAB]' not in result
        assert '"a"[TIAB]' not in result
        assert "of[TIAB]" not in result
        assert "a[TIAB]" not in result

    def test_long_phrase_retains_content_words(self) -> None:
        result = _tiab_term("implementation of a sugar-sweetened beverage SSB tax")
        assert "implementation[TIAB]" in result
        assert "beverage[TIAB]" in result
        assert "SSB[TIAB]" in result
        assert "tax[TIAB]" in result

    def test_long_phrase_uses_and_between_words(self) -> None:
        result = _tiab_term("sugary drink excise tax")
        assert " AND " in result


# ---------------------------------------------------------------------------
# 2. _build_pubmed_query — full rule-based PubMed query
# ---------------------------------------------------------------------------

class TestBuildPubmedQuery:
    def test_no_quoted_phrase_longer_than_3_words(self) -> None:
        """
        Core regression: the original bug wrapped the full 7-word phrase
        'implementation of a sugar-sweetened beverage SSB tax' in quotes,
        causing zero PubMed results.  This must never happen again.
        """
        q = _ssb_query()
        pm = _build_pubmed_query(q)
        _assert_no_long_quoted_phrases(pm)

    def test_query_contains_tiab_tags(self) -> None:
        q = _ssb_query()
        pm = _build_pubmed_query(q)
        assert "[TIAB]" in pm

    def test_query_uses_boolean_and(self) -> None:
        """Intervention and outcome concept groups are AND-combined."""
        q = _ssb_query()
        pm = _build_pubmed_query(q)
        assert " AND " in pm

    def test_query_uses_boolean_or_within_group(self) -> None:
        """Synonyms within a concept group are OR-combined."""
        q = _ssb_query()
        pm = _build_pubmed_query(q)
        assert " OR " in pm

    def test_short_synonym_soda_tax_is_quoted(self) -> None:
        """2-word phrase 'soda tax' should be preserved as an exact-phrase term."""
        q = _ssb_query()
        pm = _build_pubmed_query(q)
        assert '"soda tax"[TIAB]' in pm

    def test_override_bypasses_rule_based_logic(self) -> None:
        """When pubmed_query_override is set the connector must return it verbatim."""
        override = '(SSB[TIAB] OR "sugar tax"[TIAB]) AND (obesity[TIAB])'
        q = _ssb_query().model_copy(update={"pubmed_query_override": override})
        assert _build_pubmed_query(q) == override

    def test_year_filter_appended_when_date_range_set(self) -> None:
        q = _ssb_query().model_copy(update={"year_range": (2010, 2023)})
        pm = _build_pubmed_query(q)
        assert "2010/01/01" in pm
        assert "2023/12/31" in pm


# ---------------------------------------------------------------------------
# 3. _build_s2_query — rule-based Semantic Scholar query
# ---------------------------------------------------------------------------

class TestBuildS2Query:
    def test_no_double_quotes(self) -> None:
        """S2 does not support quoted phrases — must be bare keywords only."""
        q = _ssb_query()
        s2 = _build_s2_query(q)
        _assert_no_quotes(s2)

    def test_no_boolean_operators(self) -> None:
        """S2 bulk endpoint treats every word as a required AND — no operators."""
        q = _ssb_query()
        s2 = _build_s2_query(q)
        _assert_no_boolean_operators(s2)

    def test_at_most_five_terms(self) -> None:
        """Too many words over-constrain the S2 AND-of-words model."""
        q = _ssb_query()
        s2 = _build_s2_query(q)
        assert len(s2.split()) <= 5

    def test_contains_core_keyword(self) -> None:
        """At least one of the central intervention terms must be present."""
        q = _ssb_query()
        s2 = _build_s2_query(q).lower()
        assert any(k in s2 for k in ("ssb", "tax", "beverage", "sugar"))

    def test_override_bypasses_rule_based_logic(self) -> None:
        override = "SSB tax obesity intervention"
        q = _ssb_query().model_copy(update={"s2_query_override": override})
        assert _build_s2_query(q) == override


# ---------------------------------------------------------------------------
# 4. LLMQueryBuilder — override plumbing (mocked LLM)
# ---------------------------------------------------------------------------

class TestLLMQueryBuilder:
    _VALID_LLM_PAYLOAD = {
        "pubmed_query": (
            '(SSB[TIAB] OR "sugar tax"[TIAB] OR "soda tax"[TIAB] OR "excise tax"[TIAB])'
            ' AND (obesity[TIAB] OR BMI[TIAB] OR overweight[TIAB])'
        ),
        "semantic_scholar_query": "SSB tax obesity beverage excise",
    }

    def test_successful_llm_call_sets_pubmed_override(self) -> None:
        protocol = _ssb_protocol()
        llm = _mock_llm(_llm_response(self._VALID_LLM_PAYLOAD))

        queries = asyncio.run(LLMQueryBuilder().build_initial_queries(protocol, llm))

        assert len(queries) == 1
        assert queries[0].pubmed_query_override == self._VALID_LLM_PAYLOAD["pubmed_query"]

    def test_successful_llm_call_sets_s2_override(self) -> None:
        protocol = _ssb_protocol()
        llm = _mock_llm(_llm_response(self._VALID_LLM_PAYLOAD))

        queries = asyncio.run(LLMQueryBuilder().build_initial_queries(protocol, llm))

        assert queries[0].s2_query_override == self._VALID_LLM_PAYLOAD["semantic_scholar_query"]

    def test_llm_failure_falls_back_to_rule_based(self) -> None:
        """
        If the LLM call raises, LLMQueryBuilder must silently fall back to
        QueryBuilder — query overrides are not set.
        """
        protocol = _ssb_protocol()
        queries = asyncio.run(
            LLMQueryBuilder().build_initial_queries(protocol, _failing_llm())
        )

        assert len(queries) == 1
        assert queries[0].pubmed_query_override is None
        assert queries[0].s2_query_override is None

    def test_llm_output_satisfies_rule_of_3(self) -> None:
        """
        A representative LLM response for the SSB protocol must not contain
        quoted phrases longer than 3 words.
        """
        _assert_no_long_quoted_phrases(self._VALID_LLM_PAYLOAD["pubmed_query"])

    def test_llm_s2_output_has_no_quotes_or_booleans(self) -> None:
        s2 = self._VALID_LLM_PAYLOAD["semantic_scholar_query"]
        _assert_no_quotes(s2)
        _assert_no_boolean_operators(s2)

    def test_date_range_appended_to_llm_pubmed_query(self) -> None:
        protocol = _ssb_protocol()
        object.__setattr__(protocol, "date_range", (2010, 2022))  # bypass dataclass immutability
        llm = _mock_llm(_llm_response(self._VALID_LLM_PAYLOAD))

        queries = asyncio.run(LLMQueryBuilder().build_initial_queries(protocol, llm))

        assert "2010/01/01" in queries[0].pubmed_query_override
        assert "2022/12/31" in queries[0].pubmed_query_override


# ---------------------------------------------------------------------------
# 5. _determine_mode — refinement mode selection by result count
# ---------------------------------------------------------------------------

def _coverage_report(total_records: int, has_gaps: bool) -> CoverageReport:
    gaps = ["Keyword gap: SSB appears in 0.0% of records"] if has_gaps else []
    return CoverageReport(
        temporal_coverage={},
        keyword_coverage={},
        saturation={},
        has_gaps=has_gaps,
        identified_gaps=gaps,
        total_records=total_records,
    )


class TestDetermineMode:
    def test_zero_results_triggers_relax(self) -> None:
        assert _determine_mode(_coverage_report(0, True)) == _RefineMode.RELAX

    def test_critically_low_results_triggers_relax(self) -> None:
        assert _determine_mode(_coverage_report(5, True)) == _RefineMode.RELAX

    def test_boundary_below_threshold_triggers_relax(self) -> None:
        assert _determine_mode(_coverage_report(19, True)) == _RefineMode.RELAX

    def test_boundary_at_threshold_is_fill_gaps(self) -> None:
        assert _determine_mode(_coverage_report(20, True)) == _RefineMode.FILL_GAPS

    def test_normal_result_count_with_gaps_triggers_fill_gaps(self) -> None:
        assert _determine_mode(_coverage_report(300, True)) == _RefineMode.FILL_GAPS

    def test_high_results_triggers_narrow(self) -> None:
        assert _determine_mode(_coverage_report(8000, False)) == _RefineMode.NARROW

    def test_boundary_at_high_threshold_is_narrow(self) -> None:
        assert _determine_mode(_coverage_report(5001, False)) == _RefineMode.NARROW

    def test_adequate_results_no_gaps_returns_none(self) -> None:
        assert _determine_mode(_coverage_report(300, False)) is None

    def test_zero_results_triggers_relax_even_without_gaps(self) -> None:
        """Zero results should relax regardless of gap detection status."""
        assert _determine_mode(_coverage_report(0, False)) == _RefineMode.RELAX


# ---------------------------------------------------------------------------
# 6. SearchRefinementAgent — full flow (mocked LLM)
# ---------------------------------------------------------------------------

class TestSearchRefinementAgent:
    _RELAXED_PAYLOAD = {
        "pubmed_query": "SSB[TIAB] OR tax[TIAB] OR beverage[TIAB]",
        "semantic_scholar_query": "SSB tax beverage",
    }
    _FILL_GAPS_PAYLOAD = {
        "pubmed_query": (
            '(SSB[TIAB] OR "sugar tax"[TIAB] OR "soda tax"[TIAB])'
            ' AND (obesity[TIAB] OR BMI[TIAB])'
        ),
        "semantic_scholar_query": "SSB tax obesity BMI",
    }
    _NARROW_PAYLOAD = {
        "pubmed_query": (
            '(SSB[TIAB] OR "sugar tax"[TIAB])'
            ' AND (obesity[TIAB]) AND (children[TIAB] OR adolescents[TIAB])'
        ),
        "semantic_scholar_query": "SSB tax obesity children",
    }

    def _run_refine(
        self,
        total_records: int,
        has_gaps: bool,
        llm_payload: dict,
        iteration: int = 0,
    ) -> list[SearchQuery]:
        protocol = _ssb_protocol()
        base_query = _ssb_query()
        report = _coverage_report(total_records, has_gaps)
        llm = _mock_llm(_llm_response(llm_payload))
        return asyncio.run(
            SearchRefinementAgent().refine(
                queries=[base_query],
                coverage_report=report,
                protocol=protocol,
                llm_client=llm,
                iteration=iteration,
            )
        )

    # --- RELAX mode ---

    def test_relax_updates_pubmed_override(self) -> None:
        """Zero results → RELAX → pubmed_query_override set to LLM output."""
        queries = self._run_refine(0, True, self._RELAXED_PAYLOAD)
        assert queries[0].pubmed_query_override == self._RELAXED_PAYLOAD["pubmed_query"]

    def test_relax_updates_s2_override(self) -> None:
        queries = self._run_refine(0, True, self._RELAXED_PAYLOAD)
        assert queries[0].s2_query_override == self._RELAXED_PAYLOAD["semantic_scholar_query"]

    def test_relax_output_has_no_long_quoted_phrases(self) -> None:
        queries = self._run_refine(0, True, self._RELAXED_PAYLOAD)
        _assert_no_long_quoted_phrases(queries[0].pubmed_query_override)

    def test_relax_s2_output_has_no_quotes_or_booleans(self) -> None:
        queries = self._run_refine(0, True, self._RELAXED_PAYLOAD)
        s2 = queries[0].s2_query_override
        _assert_no_quotes(s2)
        _assert_no_boolean_operators(s2)

    # --- FILL_GAPS mode ---

    def test_fill_gaps_updates_pubmed_override(self) -> None:
        queries = self._run_refine(300, True, self._FILL_GAPS_PAYLOAD)
        assert queries[0].pubmed_query_override == self._FILL_GAPS_PAYLOAD["pubmed_query"]

    def test_fill_gaps_output_has_no_long_quoted_phrases(self) -> None:
        queries = self._run_refine(300, True, self._FILL_GAPS_PAYLOAD)
        _assert_no_long_quoted_phrases(queries[0].pubmed_query_override)

    # --- NARROW mode ---

    def test_narrow_updates_pubmed_override(self) -> None:
        queries = self._run_refine(8000, False, self._NARROW_PAYLOAD)
        assert queries[0].pubmed_query_override == self._NARROW_PAYLOAD["pubmed_query"]

    # --- No-op paths ---

    def test_no_action_when_no_gaps_and_adequate_results(self) -> None:
        """300 results, no gaps → refine() must return original queries unchanged."""
        base = _ssb_query()
        report = _coverage_report(300, False)
        llm = _mock_llm(_llm_response(self._FILL_GAPS_PAYLOAD))
        result = asyncio.run(
            SearchRefinementAgent().refine([base], report, _ssb_protocol(), llm, 0)
        )
        assert result[0].pubmed_query_override == base.pubmed_query_override

    def test_iteration_cap_returns_queries_unchanged(self) -> None:
        """At iteration >= 3 the agent must return original queries without calling the LLM."""
        base = _ssb_query()
        report = _coverage_report(0, True)  # would trigger RELAX if not capped
        llm = _mock_llm(_llm_response(self._RELAXED_PAYLOAD))
        result = asyncio.run(
            SearchRefinementAgent().refine([base], report, _ssb_protocol(), llm, iteration=3)
        )
        llm.complete.assert_not_called()
        assert result[0].pubmed_query_override == base.pubmed_query_override

    def test_llm_failure_returns_queries_unchanged(self) -> None:
        """If the LLM call fails during refinement, the original queries are returned."""
        base = _ssb_query()
        report = _coverage_report(0, True)
        result = asyncio.run(
            SearchRefinementAgent().refine(
                [base], report, _ssb_protocol(), _failing_llm(), 0
            )
        )
        assert result[0].pubmed_query_override == base.pubmed_query_override


# ---------------------------------------------------------------------------
# 7. CoverageAnalyzer — total_records propagation
# ---------------------------------------------------------------------------

class TestCoverageAnalyzerTotalRecords:
    def test_empty_corpus_sets_total_records_zero(self) -> None:
        protocol = _ssb_protocol()
        report = CoverageAnalyzer().analyze(records=[], protocol=protocol, previous_count=0)
        assert report.total_records == 0

    def test_corpus_size_reflected_in_total_records(self) -> None:
        records = [
            CandidateRecord(source_database="pubmed", title=f"Paper {i}", year=2020)
            for i in range(42)
        ]
        protocol = _ssb_protocol()
        report = CoverageAnalyzer().analyze(
            records=records, protocol=protocol, previous_count=0
        )
        assert report.total_records == 42

    def test_zero_results_triggers_all_keyword_gaps(self) -> None:
        """
        With 0 results every PICO keyword must be flagged as uncovered,
        so has_gaps=True and the refinement agent knows to RELAX.
        """
        protocol = _ssb_protocol()
        report = CoverageAnalyzer().analyze(records=[], protocol=protocol, previous_count=0)
        assert report.has_gaps is True
        assert len(report.identified_gaps) > 0
