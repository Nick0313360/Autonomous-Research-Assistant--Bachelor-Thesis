"""
tests/test_unit.py — Unit Tests (No Network, Fast)
====================================================
Run:  pytest tests/test_unit.py -v

These tests are PURE — they test logic only, never hit any API.
They run in < 5 seconds and should be green before every commit.

Coverage:
  - SearchQuery: construction, validation, serialisation
  - QueryBuilder: PubMed and S2 query format correctness
  - Deduplicator: DOI dedup, fuzzy title dedup, metadata preference
  - Domain validator: acceptance and rejection of LLM-suggested terms
  - Query expansion: term formatting, deduplication
  - paper_key identity: cross-iteration new-paper detection
  - All invalid fixture cases from fixtures.py
"""

import pytest
import sys
import os

# ── Path setup ────────────────────────────────────────────────────────────────
# Your project layout:
#   module1_searc/
#   ├── files/          ← all source modules live here (flat, no subdirs)
#   └── tests/          ← this file
#
# We insert files/ onto sys.path so that:
#   - `import search_query` resolves to files/search_query.py
#   - `import literature_handler` resolves to files/literature_handler.py
#     AND literature_handler's own bare imports (pubmed_connector, etc.)
#     also resolve correctly since files/ is on the path.
#
# Technique: __file__ gives us tests/test_unit.py → dirname = tests/
# Going one level up (os.path.join(..., "..")) gives module1_searc/
# Then join with "files" gives module1_searc/files/
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_FILES_DIR  = os.path.join(_TESTS_DIR, "..", "files")
sys.path.insert(0, os.path.abspath(_FILES_DIR))

from search_query import SearchQuery, QueryBuilder, _parse_synonyms, _pubmed_concept_group
from llm_refiner import _is_domain_relevant, expand_query
from deduplicator import deduplicate, _normalise_doi
from literature_handler import _paper_key, _paper_keys
from fixtures import QUERY_FIXTURES, REFINER_REJECTION_CASES


# =============================================================================
# SearchQuery — Construction and Validation
# =============================================================================

class TestSearchQueryConstruction:
    """Validates that SearchQuery enforces its invariants correctly."""

    def test_minimal_valid_query(self):
        sq = SearchQuery(research_question="How do LLMs automate systematic reviews?")
        assert sq.research_question
        assert sq.max_papers_per_db == 500   # default

    def test_full_pico_construction(self):
        sq = SearchQuery(
            research_question="test",
            population="systematic review, literature review",
            intervention="LLM, GPT, AI agent",
            comparison="manual review",
            outcome="PRISMA, screening",
            domain_keywords=["NLP", "PRISMA"],
            year_range=(2020, 2024),
            max_papers_per_db=300,
        )
        assert sq.population == "systematic review, literature review"
        assert sq.year_range == (2020, 2024)
        assert sq.max_papers_per_db == 300

    def test_empty_rq_raises(self):
        with pytest.raises(ValueError, match="mandatory"):
            SearchQuery(research_question="")

    def test_whitespace_rq_raises(self):
        with pytest.raises(ValueError, match="mandatory"):
            SearchQuery(research_question="   ")

    def test_limit_zero_raises(self):
        with pytest.raises(ValueError):
            SearchQuery(research_question="test", max_papers_per_db=0)

    def test_limit_above_1000_raises(self):
        # S2 bulk endpoint hard cap is 1000
        with pytest.raises(ValueError):
            SearchQuery(research_question="test", max_papers_per_db=1001)

    def test_limit_exactly_1000_is_valid(self):
        sq = SearchQuery(research_question="test", max_papers_per_db=1000)
        assert sq.max_papers_per_db == 1000

    def test_inverted_year_range_raises(self):
        with pytest.raises(ValueError, match="year_range"):
            SearchQuery(research_question="test", year_range=(2025, 2018))

    def test_equal_year_range_is_valid(self):
        sq = SearchQuery(research_question="test", year_range=(2023, 2023))
        assert sq.year_range == (2023, 2023)

    def test_serialisation_roundtrip(self):
        sq = SearchQuery(
            research_question="test question",
            population="clinical notes, EHR",
            domain_keywords=["NLP", "clinical text"],
            year_range=(2019, 2024),
            max_papers_per_db=200,
        )
        restored = SearchQuery.from_dict(sq.to_dict())
        assert sq.research_question == restored.research_question
        assert list(sq.domain_keywords) == list(restored.domain_keywords)
        assert sq.year_range == restored.year_range
        assert sq.max_papers_per_db == restored.max_papers_per_db

    def test_effective_domain_keywords_explicit(self):
        sq = SearchQuery(
            research_question="test",
            domain_keywords=["explicit_kw"],
        )
        assert sq.effective_domain_keywords() == ["explicit_kw"]

    def test_effective_domain_keywords_auto_derive(self):
        """When domain_keywords is empty, derives from PICO slots."""
        sq = SearchQuery(
            research_question="test",
            population="systematic review, literature review",
            intervention="LLM, GPT",
            outcome="PRISMA, screening",
        )
        derived = sq.effective_domain_keywords()
        assert "systematic review" in derived
        assert "LLM" in derived

    def test_effective_domain_keywords_no_pico(self):
        """With no PICO and no domain_keywords, returns empty list."""
        sq = SearchQuery(research_question="test only")
        assert sq.effective_domain_keywords() == []


# =============================================================================
# SearchQuery — All fixture cases
# =============================================================================

class TestQueryFixtures:
    """Runs every fixture from fixtures.py — valid ones construct, invalid ones raise."""

    @pytest.mark.parametrize("fixture", [f for f in QUERY_FIXTURES if f["expect_valid"]])
    def test_valid_fixtures_construct(self, fixture):
        assert fixture["query"] is not None, f"Fixture {fixture['id']} should construct"
        assert fixture["query"].research_question

    @pytest.mark.parametrize("fixture", [f for f in QUERY_FIXTURES if not f["expect_valid"]])
    def test_invalid_fixtures_raise(self, fixture):
        with pytest.raises((ValueError, TypeError)):
            SearchQuery(**fixture["query_args"])


# =============================================================================
# QueryBuilder — PubMed query structure
# =============================================================================

class TestQueryBuilderPubMed:

    def test_single_slot_no_wrapping(self):
        """One synonym in a slot → no extra parentheses needed."""
        sq = SearchQuery(
            research_question="test",
            population="systematic review",
        )
        q = QueryBuilder.build_pubmed(sq)
        assert '"systematic review"[Title/Abstract]' in q

    def test_multi_synonym_slot_uses_or(self):
        sq = SearchQuery(
            research_question="test",
            population="systematic review, literature review, scoping review",
        )
        q = QueryBuilder.build_pubmed(sq)
        assert " OR " in q
        assert '"systematic review"[Title/Abstract]' in q
        assert '"literature review"[Title/Abstract]' in q
        assert '"scoping review"[Title/Abstract]' in q

    def test_two_slots_use_and(self):
        sq = SearchQuery(
            research_question="test",
            population="systematic review",
            intervention="LLM, GPT",
        )
        q = QueryBuilder.build_pubmed(sq)
        assert " AND " in q

    def test_singleword_no_quotes(self):
        """Single-word terms should NOT be quoted in PubMed."""
        sq = SearchQuery(
            research_question="test",
            intervention="LLM, NLP, GPT",
        )
        q = QueryBuilder.build_pubmed(sq)
        assert "LLM[Title/Abstract]" in q
        assert '"LLM"' not in q   # should not be quoted

    def test_multiword_quoted(self):
        """Multi-word terms MUST be quoted."""
        sq = SearchQuery(
            research_question="test",
            intervention="large language model, AI agent",
        )
        q = QueryBuilder.build_pubmed(sq)
        assert '"large language model"[Title/Abstract]' in q
        assert '"AI agent"[Title/Abstract]' in q

    def test_fallback_no_pico(self):
        """No PICO slots → research question used as quoted phrase."""
        sq = SearchQuery(research_question="automated systematic review")
        q = QueryBuilder.build_pubmed(sq)
        assert '"automated systematic review"[Title/Abstract]' in q

    def test_year_range_appended(self):
        sq = SearchQuery(
            research_question="test",
            population="systematic review",
            year_range=(2020, 2024),
        )
        q = QueryBuilder.build_pubmed(sq)
        assert "2020" in q
        assert "2024" in q
        assert "PDAT" in q

    def test_max_length_respected(self):
        """Query must not exceed 800 chars even with many synonyms."""
        sq = SearchQuery(
            research_question="test",
            population=", ".join([f"synonym number {i} for testing" for i in range(30)]),
        )
        q = QueryBuilder.build_pubmed(sq)
        assert len(q) <= 800


# =============================================================================
# QueryBuilder — Semantic Scholar query structure
# =============================================================================

class TestQueryBuilderSemantic:

    def test_uses_keywords_not_sentence(self):
        """S2 query must be keyword-based, not the full research question sentence."""
        sq = SearchQuery(
            research_question="How do AI agents automate systematic literature review?",
            population="systematic review",
            intervention="large language model, LLM, GPT",
        )
        q = QueryBuilder.build_semantic(sq)
        # Should NOT contain question words
        assert "how" not in q.lower()
        assert "?" not in q
        # Should contain domain keywords
        assert "systematic review" in q.lower() or "large language model" in q.lower()

    def test_generic_outcome_excluded(self):
        """Generic terms like 'precision', 'recall', 'accuracy' must not appear in S2 query."""
        sq = SearchQuery(
            research_question="NLP for clinical text",
            population="clinical notes",
            intervention="BERT, transformer",
            outcome="precision, recall, accuracy, F1",   # all generic
        )
        q = QueryBuilder.build_semantic(sq)
        for generic in ["precision", "recall", "accuracy"]:
            assert generic not in q.lower(), (
                f"Generic term '{generic}' should be excluded from S2 query but found in: {q}"
            )

    def test_domain_specific_outcome_included(self):
        """Domain-specific outcome terms SHOULD appear in S2 query."""
        sq = SearchQuery(
            research_question="systematic review automation",
            population="systematic review",
            intervention="machine learning",
            outcome="PRISMA flow, data extraction",
        )
        q = QueryBuilder.build_semantic(sq)
        assert "PRISMA" in q or "data extraction" in q

    def test_max_length_respected(self):
        sq = SearchQuery(
            research_question="x " * 200,
            population="y " * 100,
            intervention="z " * 100,
        )
        q = QueryBuilder.build_semantic(sq)
        assert len(q) <= 300

    def test_fallback_no_pico(self):
        """With no PICO slots, fallback extracts key tokens from research question."""
        sq = SearchQuery(research_question="How do LLMs automate systematic reviews?")
        q = QueryBuilder.build_semantic(sq)
        assert len(q) > 0
        assert "?" not in q


# =============================================================================
# Deduplicator
# =============================================================================

class TestDeduplicator:

    def _p(self, title, doi=None, abstract="", source="test"):
        return {"title": title, "doi": doi, "abstract": abstract, "source": source}

    def test_doi_dedup_exact(self):
        papers = [
            self._p("Paper A", doi="10.1234/abc"),
            self._p("Paper A copy", doi="10.1234/abc"),
        ]
        unique, stats = deduplicate(papers)
        assert len(unique) == 1
        assert stats["doi_duplicates"] == 1

    def test_doi_normalisation_https_prefix(self):
        papers = [
            self._p("P", doi="https://doi.org/10.1234/xyz"),
            self._p("P2", doi="doi:10.1234/xyz"),
        ]
        unique, stats = deduplicate(papers)
        assert len(unique) == 1

    def test_doi_normalisation_case(self):
        papers = [
            self._p("P", doi="10.1234/ABC"),
            self._p("P2", doi="10.1234/abc"),
        ]
        unique, stats = deduplicate(papers)
        assert len(unique) == 1

    def test_fuzzy_title_dedup_near_identical(self):
        papers = [
            self._p("Machine Learning for Systematic Reviews"),
            self._p("Machine Learning for Systematic Reviews."),  # trailing dot
        ]
        unique, stats = deduplicate(papers, similarity_threshold=90)
        assert len(unique) == 1
        assert stats["title_duplicates"] == 1

    def test_fuzzy_title_distinct_kept(self):
        papers = [
            self._p("Machine Learning for Systematic Reviews"),
            self._p("Deep Learning for Clinical Decision Support"),
            self._p("NLP for Biomedical Text Mining"),
        ]
        unique, stats = deduplicate(papers)
        assert len(unique) == 3

    def test_prefers_abstract_on_doi_dup(self):
        """When DOI duplicates, keep the copy that has an abstract."""
        papers = [
            self._p("Paper A", doi="10.1/x", abstract=""),
            self._p("Paper A", doi="10.1/x", abstract="A rich and informative abstract."),
        ]
        unique, _ = deduplicate(papers)
        assert len(unique) == 1
        assert unique[0]["abstract"] == "A rich and informative abstract."

    def test_stats_structure(self):
        papers = [self._p(f"Paper {i}") for i in range(5)]
        papers.append(self._p("Paper 0"))   # exact title duplicate
        unique, stats = deduplicate(papers)
        assert "doi_duplicates" in stats
        assert "title_duplicates" in stats
        assert "total_removed" in stats
        assert "input_count" in stats
        assert "output_count" in stats
        assert stats["total_removed"] == stats["doi_duplicates"] + stats["title_duplicates"]
        assert stats["input_count"] == 6

    def test_empty_input(self):
        unique, stats = deduplicate([])
        assert unique == []
        assert stats["input_count"] == 0

    def test_single_paper(self):
        unique, stats = deduplicate([self._p("Only paper")])
        assert len(unique) == 1
        assert stats["total_removed"] == 0


# =============================================================================
# Domain Validator (LLM Refiner guard)
# =============================================================================

class TestDomainValidator:
    """
    Tests the _is_domain_relevant guard that blocks off-topic LLM suggestions.
    This is the core regression test for the "robotics in SLR search" bug.
    """

    @pytest.mark.parametrize("case", [c for c in REFINER_REJECTION_CASES if c["must_reject"]])
    def test_off_topic_terms_rejected(self, case):
        ok, reason = _is_domain_relevant(
            term=case["term"],
            domain_keywords=case["domain_keywords"],
            research_question=case["research_question"],
        )
        assert not ok, (
            f"Term '{case['term']}' should be REJECTED ({case['reason']}) "
            f"but was accepted with reason: {reason}"
        )

    @pytest.mark.parametrize("case", [c for c in REFINER_REJECTION_CASES if not c["must_reject"]])
    def test_domain_terms_accepted(self, case):
        ok, reason = _is_domain_relevant(
            term=case["term"],
            domain_keywords=case["domain_keywords"],
            research_question=case["research_question"],
        )
        assert ok, (
            f"Term '{case['term']}' should be ACCEPTED ({case['reason']}) "
            f"but was rejected with reason: {reason}"
        )

    def test_robotics_rejected_explicitly(self):
        ok, _ = _is_domain_relevant(
            term="robotics",
            domain_keywords=["systematic review", "NLP", "PRISMA", "LLM"],
            research_question="automated systematic literature review using LLMs",
        )
        assert not ok

    def test_chemistry_rejected(self):
        ok, _ = _is_domain_relevant(
            term="chemical synthesis",
            domain_keywords=["literature review", "machine learning", "healthcare"],
            research_question="machine learning for healthcare literature review",
        )
        assert not ok

    def test_substring_match_accepted(self):
        ok, reason = _is_domain_relevant(
            term="systematic review automation",
            domain_keywords=["systematic review"],
            research_question="anything",
        )
        assert ok

    def test_empty_domain_keywords(self):
        """With no anchors, validator falls back to research question only."""
        ok, _ = _is_domain_relevant(
            term="evidence synthesis",
            domain_keywords=[],
            research_question="systematic review automation evidence synthesis",
        )
        assert ok   # word overlap with research question should match


# =============================================================================
# Query Expansion
# =============================================================================

class TestQueryExpansion:

    def test_single_word_appended(self):
        result = expand_query("original query", ["BERT"])
        assert "BERT" in result
        assert result.startswith("original query OR")

    def test_multiword_quoted(self):
        result = expand_query("base query", ["evidence synthesis"])
        assert '"evidence synthesis"' in result

    def test_multiple_terms(self):
        result = expand_query("base", ["NLP", "LLM", "transformer"])
        for t in ["NLP", "LLM", "transformer"]:
            assert t in result

    def test_empty_terms_unchanged(self):
        assert expand_query("base", []) == "base"

    def test_no_mutation_of_original(self):
        original = "original query text"
        expand_query(original, ["new_term"])
        assert original == "original query text"


# =============================================================================
# Paper Key Identity
# =============================================================================

class TestPaperKey:

    def test_doi_preferred_over_title(self):
        p = {"title": "Some Paper", "doi": "10.1234/test"}
        assert _paper_key(p).startswith("doi:")

    def test_title_fallback_when_no_doi(self):
        p = {"title": "Some Paper", "doi": None}
        assert _paper_key(p).startswith("title:")

    def test_same_doi_different_source_is_duplicate(self):
        """Cross-database dedup: same DOI from PubMed and S2 must be detected."""
        pubmed_p   = {"title": "Paper A",            "doi": "10.1234/x", "source": "pubmed"}
        semantic_p = {"title": "Paper A (preprint)", "doi": "10.1234/x", "source": "semantic_scholar"}
        keys = _paper_keys([pubmed_p])
        assert _paper_key(semantic_p) in keys

    def test_doi_case_insensitive(self):
        p1 = {"title": "P", "doi": "10.1234/XYZ"}
        p2 = {"title": "P", "doi": "10.1234/xyz"}
        assert _paper_key(p1) == _paper_key(p2)

    def test_missing_title_and_doi(self):
        """Should not crash — returns a placeholder key."""
        p = {"title": "", "doi": None}
        key = _paper_key(p)
        assert isinstance(key, str)


# =============================================================================
# Helper: _parse_synonyms
# =============================================================================

class TestParseSynonyms:

    def test_comma_separated(self):
        result = _parse_synonyms("LLM, GPT, BERT")
        assert result == ["LLM", "GPT", "BERT"]

    def test_semicolon_separated(self):
        result = _parse_synonyms("LLM; GPT; BERT")
        assert result == ["LLM", "GPT", "BERT"]

    def test_strips_whitespace(self):
        result = _parse_synonyms("  LLM , GPT  ")
        assert result == ["LLM", "GPT"]

    def test_empty_string(self):
        assert _parse_synonyms("") == []

    def test_single_term(self):
        assert _parse_synonyms("systematic review") == ["systematic review"]