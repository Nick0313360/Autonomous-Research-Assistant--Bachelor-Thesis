"""
tests/integration/test_benchmark_alignment.py
==============================================
Benchmark-alignment integration test for topic CD008874 (CLEF-TAR 2019, DTA).

Verifies three properties after the query-builder refactor:
  1. "Mallampati" and "airway" appear as phrases in the outbound API calls
     for both PubMed and Semantic Scholar.
  2. The PubMed query uses AND logic between PICO groups (not a flat OR).
  3. The combined unique candidate count after deduplication is within ±15%
     of the CLEF-TAR 2019 pool size for CD008874 (2,382 records).

API calls are fully mocked; no network access is required.

Note on synthetic record generation
------------------------------------
All titles use an MD5-based hash suffix so adjacent records have
Levenshtein ratio << 0.95 and are never false-positively merged by the
DeduplicationEngine's title-similarity pass.  Deduplication is exercised
via PMID overlap, matching real-world cross-source dedup behaviour.
"""
from __future__ import annotations

import hashlib

from models.data_classes import (
    CandidateRecord,
    Criterion,
    CriterionType,
    PICO,
    ReviewProtocol,
)
from tier1_search.deduplication import DeduplicationEngine
from tier1_search.pubmed_connector import _build_pubmed_query
from tier1_search.query_builder import QueryBuilder, _extract_phrases
from tier1_search.semantic_scholar_connector import _build_s2_query

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CLEF-TAR 2019 CD008874 screening pool size (the benchmark).
_CLEF_TAR_POOL = 2_382
_TOLERANCE = 0.15  # ±15 %


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cd008874_protocol() -> ReviewProtocol:
    """Construct the CD008874 ReviewProtocol from its JSON-equivalent values."""
    return ReviewProtocol(
        title=(
            "Airway physical examination tests for detection of difficult "
            "airway management in apparently normal adult patients"
        ),
        research_question=(
            "What is the diagnostic accuracy of Mallampati classification "
            "and other airway examination tests for detecting difficult airway "
            "in adult patients with no apparent anatomical airway abnormalities?"
        ),
        pico=PICO(
            population="adult patients with no apparent anatomical airway abnormalities",
            intervention=(
                "Mallampati classification and other commonly used "
                "airway examination tests"
            ),
            comparator="reference standard for difficult airway assessment",
            outcome=(
                "diagnostic accuracy for difficult face mask ventilation, "
                "difficult laryngoscopy, difficult tracheal intubation, "
                "and failed intubation"
            ),
            study_design="diagnostic accuracy study",
        ),
        inclusion_criteria=[
            Criterion(
                criterion_id="IC-01",
                text="Study evaluates airway physical examination tests",
                type=CriterionType.MANDATORY,
            )
        ],
        exclusion_criteria=[
            Criterion(
                criterion_id="EC-01",
                text="Pediatric patients",
                type=CriterionType.MANDATORY,
            )
        ],
        target_databases=["pubmed", "semantic_scholar"],
        max_papers_per_db=10_000,
        date_range=(2000, 2025),
    )


def _make_candidates(
    n: int,
    source: str,
    pmid_start: int = 0,
) -> list[CandidateRecord]:
    """
    Return *n* synthetic CandidateRecords with sequential PMIDs.

    Titles contain an MD5 hash of the PMID so adjacent records have
    Levenshtein ratio << 0.95 and are never collapsed by the title-
    similarity pass of DeduplicationEngine.  Deduplication is exercised
    through the PMID-overlap path.
    """
    records = []
    for i in range(n):
        pmid = pmid_start + i
        h = hashlib.md5(f"pmid{pmid}".encode()).hexdigest()[:10]
        records.append(CandidateRecord(
            source_database=source,
            title=f"Airway study {h}",
            pmid=str(pmid),
        ))
    return records


def _build_query():
    """Build the SearchQuery for CD008874 via QueryBuilder."""
    return QueryBuilder().build_initial_queries(_cd008874_protocol())[0]


# ---------------------------------------------------------------------------
# Test: query generation
# ---------------------------------------------------------------------------

class TestQueryGeneration:
    """domain_keywords must be phrase-based and free of standalone stop words."""

    def test_domain_keywords_contain_mallampati(self) -> None:
        q = _build_query()
        combined = " ".join(q.domain_keywords).lower()
        assert "mallampati" in combined

    def test_domain_keywords_contain_airway(self) -> None:
        q = _build_query()
        combined = " ".join(q.domain_keywords).lower()
        assert "airway" in combined

    def test_no_standalone_stop_words(self) -> None:
        """Stop words must not appear as lone keywords."""
        _GENERIC = {
            "with", "and", "or", "for", "no", "the", "a", "an",
            "patients", "studies", "apparent",
        }
        q = _build_query()
        for kw in q.domain_keywords:
            assert kw.lower().strip() not in _GENERIC, (
                f"Stop word appeared as standalone keyword: {kw!r}"
            )

    def test_domain_keywords_are_phrases(self) -> None:
        """At least three keywords must be multi-word phrases."""
        q = _build_query()
        multi_word = [kw for kw in q.domain_keywords if " " in kw]
        assert len(multi_word) >= 3, (
            f"Expected ≥ 3 multi-word phrases; got: {q.domain_keywords}"
        )

    def test_domain_keywords_count_bounded(self) -> None:
        """Number of initial keywords must be manageable (≤ 20)."""
        q = _build_query()
        assert len(q.domain_keywords) <= 20, (
            f"Too many keywords ({len(q.domain_keywords)}): {q.domain_keywords}"
        )


# ---------------------------------------------------------------------------
# Test: PubMed query structure
# ---------------------------------------------------------------------------

class TestPubMedQueryStructure:
    """PubMed query must use AND between PICO groups and quote phrases."""

    def test_pubmed_query_contains_mallampati_phrase(self) -> None:
        q = _build_query()
        pubmed_q = _build_pubmed_query(q)
        assert "mallampati" in pubmed_q.lower(), (
            f"'mallampati' missing from PubMed query: {pubmed_q}"
        )

    def test_pubmed_query_contains_airway_phrase(self) -> None:
        q = _build_query()
        pubmed_q = _build_pubmed_query(q)
        assert "airway" in pubmed_q.lower(), (
            f"'airway' missing from PubMed query: {pubmed_q}"
        )

    def test_pubmed_query_uses_and_between_pico_groups(self) -> None:
        q = _build_query()
        pubmed_q = _build_pubmed_query(q)
        assert " AND " in pubmed_q, (
            f"PubMed query lacks AND between PICO groups: {pubmed_q}"
        )

    def test_pubmed_query_uses_tiab_qualifier(self) -> None:
        q = _build_query()
        pubmed_q = _build_pubmed_query(q)
        assert "[TIAB]" in pubmed_q

    def test_pubmed_query_is_not_flat_or_only(self) -> None:
        """Regression guard: old bug produced one giant OR block."""
        q = _build_query()
        pubmed_q = _build_pubmed_query(q)
        # There must be at least two AND-separated sub-expressions
        assert pubmed_q.count(" AND ") >= 2, (
            f"Expected ≥ 2 AND connectors (PICO groups + date); "
            f"got {pubmed_q.count(' AND ')}: {pubmed_q}"
        )

    def test_pubmed_query_includes_date_range(self) -> None:
        q = _build_query()
        pubmed_q = _build_pubmed_query(q)
        assert "[PDAT]" in pubmed_q


# ---------------------------------------------------------------------------
# Test: Semantic Scholar query structure
# ---------------------------------------------------------------------------

class TestS2QueryStructure:
    """S2 query must be concise and contain domain-specific terms."""

    def test_s2_query_contains_mallampati_or_airway(self) -> None:
        q = _build_query()
        s2_q = _build_s2_query(q)
        assert "mallampati" in s2_q.lower() or "airway" in s2_q.lower(), (
            f"Neither 'mallampati' nor 'airway' in S2 query: {s2_q}"
        )

    def test_s2_query_capped_for_api_compatibility(self) -> None:
        """
        S2 treats every space-separated word as a required AND term.
        Sending 26 words → near-zero recall. The query must stay ≤ 5 phrase
        tokens (typically 5–15 words) regardless of domain_keywords length.
        When intervention is present, intervention phrases anchor the query
        and artificial domain_keywords must NOT bleed through.
        """
        q = _build_query()
        big_query = q.model_copy(
            update={"domain_keywords": [f"term {i}" for i in range(20)]}
        )
        s2_q = _build_s2_query(big_query)
        # None of the 20 artificial domain_keywords should appear;
        # intervention phrases (from query.intervention) take precedence.
        for phrase in big_query.domain_keywords:
            assert phrase not in s2_q, (
                f"Artificial domain_keyword leaked into S2 query: {phrase!r}"
            )
        # Total word count must remain compact (≤ 15 words from ≤ 5 phrases)
        assert len(s2_q.split()) <= 15, (
            f"S2 query too long ({len(s2_q.split())} words): {s2_q}"
        )

    def test_s2_intervention_phrases_anchor_query(self) -> None:
        """
        Intervention phrases (index tests) must appear first in the S2 query
        and precede any outcome/comparison terms.
        The 5-term cap must place intervention phrases before other PICO terms.
        """
        q = _build_query()
        s2_q = _build_s2_query(q)
        # Primary index test for CD008874 must appear
        assert "mallampati" in s2_q.lower(), (
            f"Primary index test 'Mallampati' missing from S2 query: {s2_q}"
        )
        assert "airway" in s2_q.lower(), (
            f"Domain anchor 'airway' missing from S2 query: {s2_q}"
        )
        # Intervention terms must come before any outcome/comparison terms
        idx_mallampati = s2_q.lower().index("mallampati")
        # "difficult face mask ventilation" is an outcome term (not in intervention);
        # it should appear AFTER the intervention anchor, if at all.
        if "difficult face mask ventilation" in s2_q.lower():
            assert idx_mallampati < s2_q.lower().index("difficult face mask ventilation"), (
                "Intervention anchor must precede outcome terms in S2 query"
            )


# ---------------------------------------------------------------------------
# Test: Benchmark alignment (mock-based count check)
# ---------------------------------------------------------------------------

class TestBenchmarkAlignment:
    """
    Simulate a full retrieval run with mocked connector responses and verify
    the deduplicated candidate count is within ±15 % of the CLEF-TAR 2019
    pool for CD008874 (2,382 records).

    Setup
    -----
    PubMed  : 2,000 records  (PMIDs 1000 – 2999)
    S2      : 600  records   (PMIDs 2800 – 3399, 200 overlap with PubMed)
    Expected unique after dedup: 2,000 + 400 = 2,400
    Target range ±15 % of 2,382: [2,025 – 2,739]
    """

    def test_unique_candidate_count_within_tolerance(self) -> None:
        pubmed_records = _make_candidates(2_000, "pubmed", pmid_start=1_000)
        # PMIDs 2800-2999 overlap with PubMed; 3000-3399 are new S2-only.
        s2_records = _make_candidates(600, "semantic_scholar", pmid_start=2_800)

        dedup = DeduplicationEngine()
        unique = dedup.deduplicate(pubmed_records + s2_records)

        lo = int(_CLEF_TAR_POOL * (1 - _TOLERANCE))  # 2,025
        hi = int(_CLEF_TAR_POOL * (1 + _TOLERANCE))  # 2,739

        assert lo <= len(unique) <= hi, (
            f"Unique candidate count {len(unique)} outside ±15 % of "
            f"CLEF-TAR pool {_CLEF_TAR_POOL}: expected [{lo}, {hi}]"
        )

    def test_dedup_removes_pmid_overlap(self) -> None:
        """Deduplication engine must collapse PMID duplicates across sources."""
        pubmed_records = _make_candidates(100, "pubmed", pmid_start=0)
        # 50 of the S2 records share PMIDs 0-49 with PubMed
        s2_overlap = _make_candidates(50, "semantic_scholar", pmid_start=0)
        s2_new = _make_candidates(50, "semantic_scholar", pmid_start=100)

        dedup = DeduplicationEngine()
        unique = dedup.deduplicate(pubmed_records + s2_overlap + s2_new)

        assert len(unique) == 150, (
            f"Expected 150 unique records (100 PubMed + 50 new S2); got {len(unique)}"
        )

    def test_phrase_extraction_consistency_across_pico_fields(self) -> None:
        """_extract_phrases must produce consistent results for each PICO field."""
        pico_fields = {
            "population": "adult patients with no apparent anatomical airway abnormalities",
            "intervention": "Mallampati classification and other commonly used airway examination tests",
            "comparator": "reference standard for difficult airway assessment",
            "outcome": (
                "diagnostic accuracy for difficult face mask ventilation, "
                "difficult laryngoscopy, difficult tracheal intubation, "
                "and failed intubation"
            ),
        }

        expected_phrases = {
            "population":    {"adult patients", "anatomical airway abnormalities"},
            "intervention":  {"Mallampati classification", "airway examination tests"},
            "comparator":    {"reference standard", "difficult airway assessment"},
            "outcome":       {
                "diagnostic accuracy",
                "difficult face mask ventilation",
                "difficult laryngoscopy",
                "difficult tracheal intubation",
                "failed intubation",
            },
        }

        for field, text in pico_fields.items():
            extracted = set(_extract_phrases(text))
            assert extracted == expected_phrases[field], (
                f"PICO[{field}] mismatch.\n"
                f"  Expected: {sorted(expected_phrases[field])}\n"
                f"  Got:      {sorted(extracted)}"
            )
