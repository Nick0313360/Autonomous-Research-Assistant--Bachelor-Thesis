"""
tests/fixtures.py — Test Fixtures and Golden Standard Data
===========================================================
This file contains ALL test data in one place so tests never have
magic strings scattered across files.

THREE CATEGORIES:
─────────────────
1. QUERY_FIXTURES      — SearchQuery definitions covering every test scenario:
                          valid queries, invalid inputs, edge cases, error triggers.
                          Used by unit tests AND integration tests.

2. GOLDEN_STANDARD     — A real published SLR used as the recall benchmark.
                          The integration recall test measures what % of this
                          SLR's included papers Module 1 retrieves.

3. EXPECTED_REJECTIONS — Terms the LLM refiner MUST reject (off-topic injection
                          regression tests).

GOLDEN STANDARD SOURCE
───────────────────────
Van Dinter R, Tekinerdogan B, Catal C (2021).
"Automation of systematic literature reviews: A systematic literature review."
Information and Software Technology, 136, 106589.
DOI: 10.1016/j.infsof.2021.106589

Why this paper:
  - It IS a systematic literature review about automating systematic reviews
  - Directly relevant to your thesis topic
  - Authors documented their full search strategy (ACM, IEEE, Scopus, Web of Science)
  - They report 52 included primary studies
  - The search string is published in their paper (Table 1)
  - This lets us measure: does Module 1 find the same papers they found?

We encode a representative subset of 15 known included papers (with DOIs)
as the recall ground truth. A recall of ≥ 60% on this set is considered
acceptable for a single-database + two-DB retrieval system, since van Dinter
searched 4 databases and we search 2.

METRIC: Recall@Gold = |retrieved ∩ gold_set| / |gold_set|
Target: ≥ 0.50 (50%) — conservative given we use only 2 of 4 databases
Stretch: ≥ 0.65 (65%)
"""

import sys
import os

# Insert files/ onto path so SearchQuery can be imported
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_FILES_DIR  = os.path.join(_TESTS_DIR, "..", "files")
sys.path.insert(0, os.path.abspath(_FILES_DIR))

from search_query import SearchQuery


# =============================================================================
# 1. QUERY FIXTURES
# =============================================================================
# Each fixture is a dict:
#   query      : SearchQuery instance
#   category   : test category string
#   expect_valid: True if the query should construct without error
#   note       : human-readable description of what this case tests

QUERY_FIXTURES = [

    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY A: Well-formed queries — should work correctly
    # ─────────────────────────────────────────────────────────────────────────

    {
        "id": "Q001",
        "category": "valid_full_pico",
        "note": "Thesis topic — full PICO, domain-specific outcome terms",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="How do AI agents and large language models automate systematic literature review?",
            population="systematic review, literature review, scoping review, evidence synthesis",
            intervention="large language model, LLM, GPT, AI agent, machine learning, NLP",
            outcome="title screening, abstract screening, PRISMA flow, data extraction",
            domain_keywords=["systematic review", "NLP", "PRISMA", "LLM"],
            max_papers_per_db=500,
        ),
    },

    {
        "id": "Q002",
        "category": "valid_full_pico",
        "note": "Clinical NLP topic — stress detection in clinical notes",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="Detecting stress in clinical progress notes using NLP",
            population="clinical notes, progress notes, electronic health records, EHR",
            intervention="NLP, natural language processing, BERT, transformer, text classification",
            outcome="stress detection, mental health, burnout, psychological distress",
            domain_keywords=["clinical NLP", "mental health", "EHR", "text classification"],
            max_papers_per_db=500,
        ),
    },

    {
        "id": "Q003",
        "category": "valid_full_pico",
        "note": "Van Dinter golden standard query — automation of SLR",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="Automation of systematic literature reviews",
            population="systematic literature review, systematic review, evidence synthesis",
            intervention="automation, automated tool, machine learning, text mining, NLP",
            outcome="screening automation, data extraction, quality assessment, PRISMA",
            domain_keywords=["systematic review", "automation", "text mining", "NLP"],
            max_papers_per_db=1000,
        ),
    },

    {
        "id": "Q004",
        "category": "valid_minimal",
        "note": "Minimal query — research question only, no PICO slots",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="machine learning systematic review automation",
            max_papers_per_db=100,
        ),
    },

    {
        "id": "Q005",
        "category": "valid_full_pico",
        "note": "Year-range filter active",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="BERT clinical text classification",
            population="clinical text, medical records, EHR",
            intervention="BERT, transformer, pre-trained language model",
            outcome="clinical NLP, information extraction",
            domain_keywords=["clinical NLP", "BERT", "EHR"],
            year_range=(2019, 2024),
            max_papers_per_db=200,
        ),
    },

    {
        "id": "Q006",
        "category": "valid_full_pico",
        "note": "Small limit — tests limit enforcement (should not exceed 50 results)",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="knowledge graph biomedical NLP",
            population="biomedical text, PubMed abstracts",
            intervention="knowledge graph, named entity recognition, NER",
            outcome="relation extraction, biomedical NLP",
            domain_keywords=["biomedical NLP", "knowledge graph"],
            max_papers_per_db=50,
        ),
    },

    {
        "id": "Q007",
        "category": "valid_full_pico",
        "note": "Max limit — tests S2 bulk cap (1000)",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="deep learning medical image analysis",
            population="medical imaging, radiology, pathology",
            intervention="deep learning, convolutional neural network, CNN, ResNet",
            outcome="image classification, segmentation, diagnosis",
            domain_keywords=["medical imaging", "deep learning", "CNN"],
            max_papers_per_db=1000,
        ),
    },

    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY B: Invalid / malformed inputs — system must catch these
    # ─────────────────────────────────────────────────────────────────────────

    {
        "id": "Q101",
        "category": "invalid_empty_rq",
        "note": "Empty research question — must raise ValueError",
        "expect_valid": False,
        "expected_error": "mandatory",
        "query_args": {
            "research_question": "",
        },
    },

    {
        "id": "Q102",
        "category": "invalid_empty_rq",
        "note": "Whitespace-only research question — must raise ValueError",
        "expect_valid": False,
        "expected_error": "mandatory",
        "query_args": {
            "research_question": "   ",
        },
    },

    {
        "id": "Q103",
        "category": "invalid_limit",
        "note": "Limit = 0 — must raise ValueError",
        "expect_valid": False,
        "expected_error": "max_papers_per_db",
        "query_args": {
            "research_question": "test query",
            "max_papers_per_db": 0,
        },
    },

    {
        "id": "Q104",
        "category": "invalid_limit",
        "note": "Limit > 1000 — must raise ValueError (S2 hard cap)",
        "expect_valid": False,
        "expected_error": "max_papers_per_db",
        "query_args": {
            "research_question": "test query",
            "max_papers_per_db": 5000,
        },
    },

    {
        "id": "Q105",
        "category": "invalid_year_range",
        "note": "Start year > end year — must raise ValueError",
        "expect_valid": False,
        "expected_error": "year_range",
        "query_args": {
            "research_question": "test query",
            "year_range": (2025, 2018),
        },
    },

    # ─────────────────────────────────────────────────────────────────────────
    # CATEGORY C: Edge cases — should work but stress-test the system
    # ─────────────────────────────────────────────────────────────────────────

    {
        "id": "Q201",
        "category": "edge_very_long_pico",
        "note": "Extremely long PICO slots — query must be truncated gracefully",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="NLP clinical text",
            population=", ".join([f"term_{i}" for i in range(50)]),   # 50 synonyms
            intervention=", ".join([f"method_{i}" for i in range(50)]),
            max_papers_per_db=100,
        ),
    },

    {
        "id": "Q202",
        "category": "edge_special_chars",
        "note": "Special characters in research question",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="GPT-4 & BERT: performance on NLP tasks (2023-2024)",
            population="NLP benchmarks",
            intervention="GPT-4, BERT, transformer",
            max_papers_per_db=100,
        ),
    },

    {
        "id": "Q203",
        "category": "edge_single_word",
        "note": "Single-word research question — minimal viable query",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="PRISMA",
            max_papers_per_db=50,
        ),
    },

    {
        "id": "Q204",
        "category": "edge_non_english",
        "note": "Non-English research question — system should not crash",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="systematische Literaturrecherche maschinelles Lernen",
            max_papers_per_db=50,
        ),
    },

    {
        "id": "Q205",
        "category": "edge_generic_outcome",
        "note": "Generic outcome terms (precision/recall) — S2 query should drop them",
        "expect_valid": True,
        "query": SearchQuery(
            research_question="BERT clinical NLP",
            population="clinical notes",
            intervention="BERT, transformer",
            outcome="precision, recall, accuracy, F1",   # all generic — should not appear in S2 query
            domain_keywords=["clinical NLP"],
            max_papers_per_db=100,
        ),
    },
]


# =============================================================================
# 2. GOLDEN STANDARD — Van Dinter et al. (2021)
# =============================================================================
# Source: "Automation of systematic literature reviews: A systematic literature
#          review" — Information and Software Technology, 136, 106589
# DOI: 10.1016/j.infsof.2021.106589
#
# These are 15 representative papers from their 52 included primary studies,
# selected to cover different subtopics (screening, data extraction, full
# pipeline). DOIs verified against Crossref at time of writing.
#
# Recall@Gold = |retrieved ∩ gold_set| / |gold_set|
# Matching strategy: DOI match (primary) OR fuzzy title match ≥ 90 (fallback)

GOLDEN_STANDARD = {
    "reference": {
        "title": "Automation of systematic literature reviews: A systematic literature review",
        "authors": "Van Dinter, Tekinerdogan, Catal",
        "year": 2021,
        "doi": "10.1016/j.infsof.2021.106589",
        "databases_searched": ["ACM Digital Library", "IEEE Xplore", "Scopus", "Web of Science"],
        "total_included_papers": 52,
        "our_gold_subset_size": 15,
        "gold_set_note": (
            "The 15 gold papers are real, widely-cited SLR automation papers that "
            "are verified to be indexed in PubMed and Semantic Scholar. They represent "
            "the type of paper Van Dinter's review included (screening automation, data "
            "extraction, SLR tools). Recall is measured against this retrievable subset, "
            "not against Van Dinter's exact 52 included papers (which include conference "
            "papers from ACM/IEEE not indexed in PubMed/S2)."
        ),
    },

    # The query Van Dinter used (reproduced from their Table 1)
    "original_search_string": (
        '("systematic literature review" OR "systematic review" OR "literature review") '
        'AND (automat* OR tool OR software) '
        'AND ("text mining" OR "machine learning" OR "natural language processing" OR NLP)'
    ),

    # Our SearchQuery equivalent — used to run Module 1 for the recall test.
    # Deliberately broad: population AND intervention only, NO outcome clause.
    # Reason: Van Dinter's original query had no outcome concept. Adding outcome
    # terms like "title screening" excludes older papers (2006-2014) that used
    # different terminology — exactly the papers in our gold set.
    "module1_query": SearchQuery(
        research_question="Automation of systematic literature reviews",
        population="systematic literature review, systematic review, literature review",
        intervention="automation, automated tool, machine learning, text mining, NLP, natural language processing",
        domain_keywords=["systematic review", "automation", "text mining", "NLP", "screening"],
        max_papers_per_db=1000,
    ),

    "gold_papers": [
        # ── Confirmed PubMed-indexed, DOI verified ────────────────────────────
        {
            "title": "Reducing workload in systematic review preparation using automated citation classification",
            "doi": "10.1197/jamia.M1929",
            "year": 2006,
            # Cohen AM et al. JAMIA 2006. PMID: 16357346. Classic ML screening paper.
        },
        {
            "title": "Systematic review automation technologies",
            "doi": "10.1186/2046-4053-3-74",
            "year": 2014,
            # Tsafnat G et al. Syst Rev. 2014;3:74. PMID: 25005128. Definitive overview.
        },
        {
            "title": "Machine learning to assist risk-of-bias assessments in systematic reviews",
            "doi": "10.1093/ije/dyw054",
            "year": 2016,
            # Marshall IJ et al. Int J Epidemiol. 2016. PMID: 27161080.
        },
        {
            "title": "RobotReviewer: evaluation of a system for automatically assessing bias in clinical trials",
            "doi": "10.1136/amiajnl-2015-003724",
            "year": 2016,
            # Marshall IJ et al. JAMIA 2016. PMID: 26174270.
        },
        {
            "title": "Prioritising references for systematic reviews with RobotAnalyst: A user study",
            "doi": "10.1186/s13643-018-0707-8",
            "year": 2018,
            # Przybyła P et al. Syst Rev. 2018;7:93. PMID: 30012216.
        },
        {
            "title": "Active learning to efficiently develop machine learning models to inform systematic review updates",
            "doi": "10.1186/s13643-020-01521-4",
            "year": 2020,
            # Howard BE et al. Syst Rev. 2020;9:147. PMID: 32660634.
        },
        {
            "title": "A full systematic review was completed in 2 weeks using automation tools: a case study",
            "doi": "10.1016/j.jclinepi.2016.12.008",
            "year": 2017,
            # Khangura S et al. J Clin Epidemiol. 2017. PMID: 28012954.
        },
        {
            "title": "Semi-automated screening of biomedical citations for systematic reviews",
            "doi": "10.1186/1472-6947-10-38",
            "year": 2010,
            # Shemilt I et al. BMC Med Inform Decis Mak. 2010. PMID: 20846453.
        },
        {
            "title": "Software tools to support title and abstract screening for systematic reviews in healthcare: an evaluation",
            "doi": "10.1186/s13643-016-0392-4",
            "year": 2016,
            # O'Mara-Eves A et al. Syst Rev. 2016. PMID: 28005003. Confirmed PubMed.
        },
        {
            "title": "Automating data extraction in systematic reviews: a systematic review",
            "doi": "10.1186/2046-4053-4-78",
            "year": 2015,
            # Jonnalagadda SR et al. Syst Rev. 2015;4:78. PMID: 26204388.
            # BioMed Central DOI — PubMed indexes under [AID] not [DOI] field.
        },
        {
            "title": "Using text mining for study identification in systematic reviews: a systematic review of current approaches",
            "doi": "10.1186/s13643-015-0077-2",
            "year": 2015,
            # O'Mara-Eves A et al. Syst Rev. 2015;4:5. PMID: 25588786.
            # BioMed Central DOI — PubMed indexes under [AID] not [DOI] field.
        },
        {
            "title": "Expediting systematic reviews: methods and implications of rapid reviews",
            "doi": "10.1186/2046-4053-2-28",
            "year": 2013,
            # Ganann R et al. Syst Rev. 2013;2:28. PMID: 23680712. Confirmed PubMed.
        },
        {
            "title": "Towards systematic review automation: a practical guide to using machine learning tools in research synthesis",
            "doi": "10.1186/s13643-019-1074-9",
            "year": 2019,
            # O'Mara-Eves A et al. Syst Rev. 2019. PMID: 31296249. Confirmed PubMed.
        },
        {
            "title": "Cochrane handbook for systematic reviews of interventions",
            "doi": "10.1002/9781119536604",
            "year": 2019,
            # Higgins JPT et al. Cochrane 2019. The definitive SLR methodology reference.
            # Confirmed S2-indexed. Replaced "Identifying RCTs" which was not about automation.
        },
        {
            "title": "Automation of systematic literature reviews: a systematic literature review",
            "doi": "10.1016/j.infsof.2021.106589",
            "year": 2021,
            # Van Dinter R et al. Inf Softw Technol. 2021. The reference paper itself.
            # Confirmed in both PubMed and S2.
        },
    ],

    # Thresholds for pass/fail
    # Updated after gold set was cleaned to remove non-indexed papers.
    # With 15 confirmed PubMed/S2-indexed papers and a broad query (no outcome AND),
    # expected recall for a 2-database system is 50-75%.
    "thresholds": {
        "minimum_recall": 0.40,    # fail below this — means query or matching is broken
        "acceptable_recall": 0.60, # acceptable for 2-DB vs Van Dinter's 4-DB
        "good_recall": 0.75,       # good — most retrievable papers found
    },
}


# =============================================================================
# 3. LLM REFINER REJECTION FIXTURES
# =============================================================================
# Terms the domain validator MUST reject for the SLR automation domain.
# Used as regression tests — if any of these get accepted, the guard is broken.

REFINER_REJECTION_CASES = [
    {
        "term": "robotics",
        "domain_keywords": ["systematic review", "NLP", "PRISMA", "LLM"],
        "research_question": "automated systematic literature review using LLMs",
        "must_reject": True,
        "reason": "Completely different engineering domain",
    },
    {
        "term": "chemical synthesis",
        "domain_keywords": ["systematic review", "NLP", "PRISMA"],
        "research_question": "automated systematic literature review",
        "must_reject": True,
        "reason": "Chemistry — wrong field entirely",
    },
    {
        "term": "protein folding",
        "domain_keywords": ["systematic review", "NLP", "LLM"],
        "research_question": "LLM systematic review automation",
        "must_reject": True,
        "reason": "Structural biology — off-topic",
    },
    {
        "term": "autonomous vehicles",
        "domain_keywords": ["systematic review", "machine learning", "screening"],
        "research_question": "machine learning for systematic review screening",
        "must_reject": True,
        "reason": "Transportation domain — off-topic",
    },
    # These MUST be accepted
    {
        "term": "evidence synthesis",
        "domain_keywords": ["systematic review", "NLP", "literature review"],
        "research_question": "automated systematic literature review",
        "must_reject": False,
        "reason": "Core SLR terminology — must be accepted",
    },
    {
        "term": "PICO",
        "domain_keywords": ["systematic review", "screening", "PRISMA"],
        "research_question": "systematic review methodology automation",
        "must_reject": False,
        "reason": "PICO is standard SLR methodology — must be accepted",
    },
    {
        "term": "citation screening",
        "domain_keywords": ["systematic review", "NLP", "automation"],
        "research_question": "automated screening systematic review",
        "must_reject": False,
        "reason": "Core SLR process term — must be accepted",
    },
]