"""
tests/test_module1.py — Unit tests for Module 1
================================================
Run with:  pytest tests/test_module1.py -v

Coverage
--------
- SearchQuery validation and serialisation
- QueryBuilder output format
- LLM refiner domain filtering (the core bug fix)
- Deduplicator correctness
- _paper_key identity logic
"""

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from slr_agent.module1_search.services.search_query import SearchQuery, QueryBuilder
from slr_agent.services.llm_refiner import _is_domain_relevant, expand_query, RefinementResult
from slr_agent.module1_search.services.deduplicator import deduplicate, _normalise_doi
from slr_agent.module1_search.services.literature_handler import _paper_key, _paper_keys


# ============================================================
# SearchQuery — validation
# ============================================================

class TestSearchQuery:

    def test_minimal_valid(self):
        sq = SearchQuery(research_question="How do LLMs automate systematic reviews?")
        assert sq.research_question

    def test_empty_rq_raises(self):
        with pytest.raises(ValueError, match="mandatory"):
            SearchQuery(research_question="")

    def test_invalid_limit_raises(self):
        with pytest.raises(ValueError):
            SearchQuery(research_question="test", max_papers_per_db=0)
        with pytest.raises(ValueError):
            SearchQuery(research_question="test", max_papers_per_db=99999)

    def test_year_range_validation(self):
        with pytest.raises(ValueError):
            SearchQuery(research_question="test", year_range=(2025, 2020))

    def test_serialisation_roundtrip(self):
        sq = SearchQuery(
            research_question="test question",
            population="clinical notes",
            domain_keywords=["NLP", "systematic review"],
            year_range=(2019, 2024),
            max_papers_per_db=200,
        )
        sq2 = SearchQuery.from_dict(sq.to_dict())
        assert sq.research_question == sq2.research_question
        assert sq.domain_keywords   == list(sq2.domain_keywords)
        assert sq.year_range        == sq2.year_range


# ============================================================
# QueryBuilder
# ============================================================

class TestQueryBuilder:

    def test_pubmed_contains_title_abstract_tag(self):
        sq = SearchQuery(
            research_question="machine learning clinical notes",
            intervention="BERT transformer",
        )
        q = QueryBuilder.build_pubmed(sq)
        assert "[Title/Abstract]" in q

    def test_pubmed_year_range(self):
        sq = SearchQuery(
            research_question="NLP stress detection",
            year_range=(2020, 2024),
        )
        q = QueryBuilder.build_pubmed(sq)
        assert "2020" in q and "2024" in q

    def test_semantic_includes_domain_keywords(self):
        sq = SearchQuery(
            research_question="automated systematic review",
            domain_keywords=["PRISMA", "LLM", "screening"],
        )
        q = QueryBuilder.build_semantic(sq)
        # At least one domain keyword should appear
        assert any(kw.lower() in q.lower() for kw in sq.domain_keywords)

    def test_query_max_length(self):
        # Extremely long question should be truncated
        sq = SearchQuery(
            research_question="x " * 400,
            max_papers_per_db=100,
        )
        q = QueryBuilder.build_semantic(sq)
        assert len(q) <= 500


# ============================================================
# Domain Validator — core bug fix test
# ============================================================

class TestDomainValidator:

    def test_relevant_term_accepted(self):
        ok, reason = _is_domain_relevant(
            term="BERT",
            domain_keywords=["NLP", "clinical text", "systematic review"],
            research_question="How do NLP models automate literature review?",
        )
        assert ok

    def test_off_topic_term_rejected(self):
        # "robotics" should be rejected for an NLP / systematic review domain
        ok, reason = _is_domain_relevant(
            term="robotics",
            domain_keywords=["NLP", "clinical text", "systematic review", "PRISMA"],
            research_question="automated systematic review using LLMs",
        )
        assert not ok
        assert reason == "off_topic"

    def test_chemistry_rejected(self):
        ok, reason = _is_domain_relevant(
            term="chemical synthesis",
            domain_keywords=["literature review", "machine learning", "healthcare"],
            research_question="machine learning for healthcare literature review",
        )
        assert not ok

    def test_substring_match(self):
        ok, reason = _is_domain_relevant(
            term="systematic review automation",
            domain_keywords=["systematic review"],
            research_question="anything",
        )
        assert ok


# ============================================================
# Query expansion
# ============================================================

class TestExpandQuery:

    def test_single_word_term(self):
        result = expand_query("original query", ["BERT"])
        assert "BERT" in result
        assert result.startswith("original query OR")

    def test_multiword_term_quoted(self):
        result = expand_query("base query", ["evidence synthesis"])
        assert '"evidence synthesis"' in result

    def test_empty_terms_unchanged(self):
        assert expand_query("base", []) == "base"

    def test_multiple_terms(self):
        result = expand_query("base", ["NLP", "LLM", "transformer"])
        for t in ["NLP", "LLM", "transformer"]:
            assert t in result


# ============================================================
# Deduplicator
# ============================================================

class TestDeduplicator:

    def _paper(self, title, doi=None, abstract=""):
        return {"title": title, "doi": doi, "abstract": abstract, "source": "test"}

    def test_doi_deduplication(self):
        papers = [
            self._paper("Paper A", doi="10.1234/abc"),
            self._paper("Paper A duplicate", doi="10.1234/abc"),
        ]
        unique, stats = deduplicate(papers)
        assert len(unique) == 1
        assert stats["doi_duplicates"] == 1

    def test_doi_normalisation(self):
        papers = [
            self._paper("P", doi="https://doi.org/10.1234/xyz"),
            self._paper("P2", doi="doi:10.1234/xyz"),
        ]
        unique, stats = deduplicate(papers)
        assert len(unique) == 1

    def test_fuzzy_title_dedup(self):
        papers = [
            self._paper("Machine Learning for Clinical Notes"),
            self._paper("Machine Learning for Clinical Notes."),  # near-identical
        ]
        unique, stats = deduplicate(papers, similarity_threshold=90)
        assert len(unique) == 1
        assert stats["title_duplicates"] == 1

    def test_distinct_papers_kept(self):
        papers = [
            self._paper("Paper on NLP"),
            self._paper("Paper on Robotics"),
            self._paper("Paper on Computer Vision"),
        ]
        unique, stats = deduplicate(papers)
        assert len(unique) == 3

    def test_prefers_abstract_on_doi_dup(self):
        papers = [
            self._paper("Paper A", doi="10.1/x", abstract=""),
            self._paper("Paper A", doi="10.1/x", abstract="Full abstract here"),
        ]
        unique, _ = deduplicate(papers)
        assert unique[0]["abstract"] == "Full abstract here"

    def test_stats_totals(self):
        papers = [self._paper(f"P {i}") for i in range(10)]
        papers.append(self._paper("P 0"))   # duplicate of first
        unique, stats = deduplicate(papers)
        assert stats["input_count"] == 11
        assert stats["output_count"] == len(unique)
        assert stats["total_removed"] == stats["doi_duplicates"] + stats["title_duplicates"]


# ============================================================
# Paper key identity (cross-iteration new-paper detection)
# ============================================================

class TestPaperKey:

    def test_doi_preferred(self):
        p = {"title": "Some Paper", "doi": "10.1234/test"}
        assert _paper_key(p).startswith("doi:")

    def test_title_fallback(self):
        p = {"title": "Some Paper", "doi": None}
        assert _paper_key(p).startswith("title:")

    def test_cross_db_same_doi_detected(self):
        pubmed_p   = {"title": "Paper A", "doi": "10.1234/x", "source": "pubmed"}
        semantic_p = {"title": "Paper A (preprint)", "doi": "10.1234/x", "source": "semantic_scholar"}
        keys = _paper_keys([pubmed_p])
        assert _paper_key(semantic_p) in keys
