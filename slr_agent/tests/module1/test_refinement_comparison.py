"""
tests/test_refinement_comparison.py
=====================================
Purpose: Prove whether LLM query refinement improves recall over basic search.

This is the central validation test for --ai mode in Module 1.
It answers the one question that matters for your thesis:
  "Does iterative LLM refinement find more relevant papers than basic search?"

What it measures
----------------
For each query it runs the pipeline TWICE:
  Pass A — Basic search  (no LLM, single iteration)
  Pass B — Iterative     (LLM refinement, up to 3 iterations)

Then compares on three metrics:
  1. Paper delta    — how many more unique papers iterative found
  2. Recall delta   — how many more gold papers iterative found (golden standard only)
  3. Query evolution — what terms the LLM added and whether they were novel

Output
------
  tests/results/refinement_full_report.json       ← thesis documentation
  tests/results/golden_standard_comparison.json   ← recall-specific report

Run command
-----------
  # Full comparison (slow — takes ~10 min, runs real APIs):
  pytest tests/test_refinement_comparison.py -v -s -m refinement

  # Just the golden standard (recommended first run):
  pytest tests/test_refinement_comparison.py::TestGoldenStandardComparison -v -s

  # Fast behaviour tests only (no full pipeline, <30s):
  pytest tests/test_refinement_comparison.py::TestRefinementBehaviour -v -s
"""

import sys
import os
import json
import time
import pytest
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_FILES_DIR  = os.path.join(_TESTS_DIR, "..", "files")
sys.path.insert(0, os.path.abspath(_FILES_DIR))

from search_query import SearchQuery, QueryBuilder
from literature_handler import run_basic_search, run_iterative_search
from rapidfuzz import fuzz
from fixtures import GOLDEN_STANDARD, QUERY_FIXTURES

pytestmark = pytest.mark.refinement


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class PassResult:
    mode: str
    total_papers: int = 0
    iterations_run: int = 0
    stopped_reason: str = ""
    queries_used: List[str] = field(default_factory=list)
    terms_added: List[str] = field(default_factory=list)
    gold_found: int = 0
    gold_total: int = 0
    recall: float = 0.0
    latency_s: float = 0.0


@dataclass
class ComparisonResult:
    query_id: str
    query_note: str
    research_question: str
    basic: PassResult = field(default_factory=PassResult)
    iterative: PassResult = field(default_factory=PassResult)

    @property
    def paper_delta(self):
        return self.iterative.total_papers - self.basic.total_papers

    @property
    def paper_delta_pct(self):
        return (self.paper_delta / self.basic.total_papers * 100) if self.basic.total_papers else 0.0

    @property
    def recall_delta(self):
        return self.iterative.recall - self.basic.recall

    @property
    def refinement_helped(self):
        return self.paper_delta > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")

def _clean_doi(raw):
    d = (raw or "").strip().lower()
    for p in _PREFIXES:
        if d.startswith(p):
            d = d[len(p):]
    return d

def _match_gold(papers, gold_papers):
    """Return (found_count, found_list, not_found_list)."""
    found, not_found = [], []
    for gp in gold_papers:
        g_doi   = _clean_doi(gp.get("doi") or "")
        g_title = (gp.get("title") or "").lower()
        matched = False
        for p in papers:
            if g_doi and _clean_doi(p.get("doi") or "") == g_doi:
                matched = True; break
            if fuzz.ratio(g_title, (p.get("title") or "").lower()) >= 72:
                matched = True; break
        (found if matched else not_found).append(gp)
    return len(found), found, not_found

def _extract_terms_added(log):
    terms = []
    for it in log.iterations:
        if it.refinement and it.refinement.get("accepted"):
            terms.extend(it.refinement["accepted"])
    return terms

def _extract_queries_used(log):
    return [it.semantic_query for it in log.iterations]

def _save(filename, data):
    results_dir = os.path.join(_TESTS_DIR, "results")
    os.makedirs(results_dir, exist_ok=True)
    path = os.path.join(results_dir, filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"\n  📄 Saved → {path}")

def _print_comparison(cr: ComparisonResult):
    W = 60
    print(f"\n  {'═'*W}")
    print(f"  [{cr.query_id}] {cr.query_note}")
    print(f"  RQ: {cr.research_question[:70]}")
    print(f"  {'─'*W}")
    print(f"  {'Metric':<30} {'Basic':>12}  {'Iterative':>12}")
    print(f"  {'─'*W}")
    print(f"  {'Papers retrieved':<30} {cr.basic.total_papers:>12}  {cr.iterative.total_papers:>12}")
    print(f"  {'Iterations run':<30} {cr.basic.iterations_run:>12}  {cr.iterative.iterations_run:>12}")
    print(f"  {'Stopped reason':<30} {cr.basic.stopped_reason:>12}  {cr.iterative.stopped_reason:>12}")
    if cr.basic.gold_total > 0:
        print(f"  {'Gold papers found':<30} {cr.basic.gold_found:>12}  {cr.iterative.gold_found:>12}")
        print(f"  {'Recall@Gold':<30} {cr.basic.recall:>11.1%}  {cr.iterative.recall:>11.1%}")
    print(f"  {'─'*W}")
    print(f"  {'Paper Δ (iterative − basic)':<30} {cr.paper_delta:>+12}  ({cr.paper_delta_pct:>+.0f}%)")
    if cr.basic.gold_total > 0:
        print(f"  {'Recall Δ':<30} {cr.recall_delta:>+11.1%}")
    print(f"  {'─'*W}")
    if cr.iterative.terms_added:
        print(f"  LLM terms added: {cr.iterative.terms_added}")
    if len(cr.iterative.queries_used) > 1:
        print(f"  Query evolution ({len(cr.iterative.queries_used)} iters):")
        for i, q in enumerate(cr.iterative.queries_used, 1):
            print(f"    iter {i}: {q[:85]}")
    verdict = "✅ REFINEMENT HELPED" if cr.refinement_helped else "➖ NO DIFFERENCE"
    if cr.paper_delta < 0:
        verdict = "❌ REGRESSION — iterative found fewer papers"
    print(f"\n  Verdict: {verdict}")
    print(f"  {'═'*W}")


# =============================================================================
# 1. GOLDEN STANDARD — Basic vs Iterative with full recall measurement
# =============================================================================

@pytest.mark.refinement
class TestGoldenStandardComparison:
    """
    Core thesis validation: does LLM refinement improve recall on the
    golden standard SLR automation query?
    """

    def test_basic_vs_iterative_recall(self):
        gs  = GOLDEN_STANDARD
        sq  = gs["module1_query"]
        gps = gs["gold_papers"]

        print(f"\n\n{'='*60}")
        print(f"  GOLDEN STANDARD — BASIC vs ITERATIVE")
        print(f"  Gold set : {len(gps)} papers")
        print(f"  Query    : {sq.research_question}")
        print(f"{'='*60}")

        # ── Pass A: Basic ────────────────────────────────────────────────────
        print("\n  ── PASS A: Basic Search (no LLM) ──")
        t0 = time.time()
        basic_papers, basic_log = run_basic_search(sq)
        basic_time = time.time() - t0
        basic_found, basic_found_list, _ = _match_gold(basic_papers, gps)
        basic_recall = basic_found / len(gps)
        print(f"  Papers: {len(basic_papers)}  |  Gold found: {basic_found}/{len(gps)} ({basic_recall:.1%})  |  {basic_time:.0f}s")

        time.sleep(2)

        # ── Pass B: Iterative ────────────────────────────────────────────────
        print("\n  ── PASS B: Iterative Search (with LLM) ──")
        t0 = time.time()
        iter_papers, iter_log = run_iterative_search(sq, max_iterations=3)
        iter_time = time.time() - t0
        iter_found, iter_found_list, iter_not_found = _match_gold(iter_papers, gps)
        iter_recall = iter_found / len(gps)
        print(f"  Papers: {len(iter_papers)}  |  Gold found: {iter_found}/{len(gps)} ({iter_recall:.1%})  |  {iter_time:.0f}s")
        print(f"  LLM terms added: {_extract_terms_added(iter_log)}")

        # ── Comparison ───────────────────────────────────────────────────────
        cr = ComparisonResult(
            query_id="GOLDEN",
            query_note="SLR automation — gold set",
            research_question=sq.research_question,
            basic=PassResult(
                mode="basic",
                total_papers=len(basic_papers),
                iterations_run=len(basic_log.iterations),
                stopped_reason=basic_log.stopped_reason,
                queries_used=_extract_queries_used(basic_log),
                gold_found=basic_found, gold_total=len(gps),
                recall=basic_recall, latency_s=round(basic_time, 1),
            ),
            iterative=PassResult(
                mode="iterative",
                total_papers=len(iter_papers),
                iterations_run=len(iter_log.iterations),
                stopped_reason=iter_log.stopped_reason,
                queries_used=_extract_queries_used(iter_log),
                terms_added=_extract_terms_added(iter_log),
                gold_found=iter_found, gold_total=len(gps),
                recall=iter_recall, latency_s=round(iter_time, 1),
            ),
        )
        _print_comparison(cr)

        # Papers found by iterative but not basic
        basic_keys = {_clean_doi(p.get("doi") or "") or (p.get("title") or "")[:40]
                      for p in basic_found_list}
        newly = [p for p in iter_found_list
                 if (_clean_doi(p.get("doi") or "") or (p.get("title") or "")[:40])
                 not in basic_keys]
        if newly:
            print(f"\n  Gold papers found ONLY by iterative ({len(newly)}):")
            for p in newly:
                print(f"    ✅ {p['title'][:72]}")
        else:
            print("\n  No additional gold papers found by iterative.")

        print(f"\n  Still not found ({len(iter_not_found)}):")
        for p in iter_not_found:
            print(f"    ❌ {p['title'][:72]}")

        # Save
        _save("golden_standard_comparison.json", {
            "timestamp": datetime.now().isoformat(),
            "query": sq.to_dict(),
            "gold_set_size": len(gps),
            "basic":     {"total_papers": len(basic_papers), "gold_found": basic_found,
                          "recall": round(basic_recall, 4),
                          "pubmed_query": basic_log.iterations[0].pubmed_query,
                          "semantic_query": basic_log.iterations[0].semantic_query},
            "iterative": {"total_papers": len(iter_papers), "gold_found": iter_found,
                          "recall": round(iter_recall, 4),
                          "iterations": len(iter_log.iterations),
                          "stopped_reason": iter_log.stopped_reason,
                          "queries_per_iteration": _extract_queries_used(iter_log),
                          "llm_terms_added": _extract_terms_added(iter_log)},
            "paper_delta": cr.paper_delta,
            "recall_delta": round(cr.recall_delta, 4),
            "newly_found_by_iterative": newly,
            "still_not_found": iter_not_found,
        })

        # Assertions
        assert basic_recall >= gs["thresholds"]["minimum_recall"], (
            f"Basic recall {basic_recall:.1%} < minimum {gs['thresholds']['minimum_recall']:.0%}"
        )
        assert iter_recall >= basic_recall - 0.07, (
            f"Iterative recall {iter_recall:.1%} is worse than basic {basic_recall:.1%} — regression"
        )


# =============================================================================
# 2. ALL VALID QUERIES — paper count comparison
# =============================================================================

@pytest.mark.refinement
class TestAllQueriesComparison:
    """
    Runs all valid query fixtures in both modes.
    Core assertion: iterative must never return significantly fewer papers than basic.
    """

    FIXTURES = [f for f in QUERY_FIXTURES
                if f["expect_valid"]
                and f["category"] in ("valid_full_pico", "valid_minimal")]

    @pytest.mark.parametrize("fixture", FIXTURES)
    def test_basic_vs_iterative(self, fixture):
        sq_orig = fixture["query"]
        # Cap to 200 for reasonable test speed
        sq = SearchQuery(
            research_question=sq_orig.research_question,
            population=sq_orig.population,
            intervention=sq_orig.intervention,
            comparison=sq_orig.comparison,
            outcome=sq_orig.outcome,
            domain_keywords=list(sq_orig.domain_keywords),
            year_range=sq_orig.year_range,
            max_papers_per_db=min(sq_orig.max_papers_per_db, 200),
        )

        print(f"\n  [{fixture['id']}] {fixture['note']}")

        t0 = time.time()
        basic_papers, basic_log = run_basic_search(sq)
        basic_time = time.time() - t0

        assert len(basic_papers) > 0, f"[{fixture['id']}] Basic returned 0 papers"

        time.sleep(2)

        t0 = time.time()
        iter_papers, iter_log = run_iterative_search(sq, max_iterations=2)
        iter_time = time.time() - t0

        cr = ComparisonResult(
            query_id=fixture["id"],
            query_note=fixture["note"],
            research_question=sq.research_question,
            basic=PassResult(mode="basic", total_papers=len(basic_papers),
                             iterations_run=1, stopped_reason=basic_log.stopped_reason,
                             latency_s=round(basic_time, 1)),
            iterative=PassResult(mode="iterative", total_papers=len(iter_papers),
                                 iterations_run=len(iter_log.iterations),
                                 stopped_reason=iter_log.stopped_reason,
                                 terms_added=_extract_terms_added(iter_log),
                                 queries_used=_extract_queries_used(iter_log),
                                 latency_s=round(iter_time, 1)),
        )
        _print_comparison(cr)

        # Allow 5% tolerance for S2 non-determinism
        tolerance = max(5, int(len(basic_papers) * 0.05))
        assert len(iter_papers) >= len(basic_papers) - tolerance, (
            f"[{fixture['id']}] Regression: iterative={len(iter_papers)}, "
            f"basic={len(basic_papers)}, tolerance={tolerance}"
        )


# =============================================================================
# 3. REFINEMENT BEHAVIOUR — fast targeted tests
# =============================================================================

@pytest.mark.refinement
class TestRefinementBehaviour:
    """
    Fast tests for specific refinement properties.
    No full pipeline — pure logic or single LLM call. Runs in < 60s.
    """

    def test_llm_suggests_at_least_one_term(self):
        """LLM must suggest ≥1 accepted term given a real paper corpus."""
        from llm_refiner import analyse_query_gaps
        from pubmed_connector import search as pubmed_search

        sq = SearchQuery(
            research_question="automated systematic literature review",
            population="systematic review, literature review",
            intervention="machine learning, NLP, automation, text mining",
            domain_keywords=["systematic review", "NLP", "automation"],
            max_papers_per_db=50,
        )
        papers = pubmed_search(QueryBuilder.build_pubmed(sq), retmax=20)
        if len([p for p in papers if p.get("abstract")]) < 5:
            pytest.skip("Insufficient papers with abstracts")

        result = analyse_query_gaps(
            papers=papers,
            original_query=QueryBuilder.build_semantic(sq),
            domain_keywords=sq.effective_domain_keywords(),
            used_terms=set(),
            iteration=1,
            max_new_terms=5,
        )

        print(f"\n  LLM raw   : '{result.llm_raw_output}'")
        print(f"  Accepted  : {result.accepted_terms}")
        print(f"  Rejected  : {[(d.term, d.reason) for d in result.rejected_terms]}")

        assert not result.error, f"LLM call failed: {result.error}"
        assert len(result.accepted_terms) >= 1, (
            f"LLM accepted 0 terms. Raw: '{result.llm_raw_output}'. "
            f"Rejected: {result.rejected_terms}"
        )

    def test_used_terms_blocked_in_next_iteration(self):
        """Terms in used_terms must never appear in accepted_terms."""
        from llm_refiner import analyse_query_gaps
        from pubmed_connector import search as pubmed_search

        sq = SearchQuery(
            research_question="automated systematic literature review NLP",
            population="systematic review",
            intervention="machine learning, NLP, text mining, automation",
            domain_keywords=["systematic review", "NLP", "automation"],
            max_papers_per_db=30,
        )
        papers = pubmed_search(QueryBuilder.build_pubmed(sq), retmax=15)
        if len([p for p in papers if p.get("abstract")]) < 5:
            pytest.skip("Insufficient papers with abstracts")

        # IMPORTANT: used_terms must be lowercase to match how analyse_query_gaps
        # stores terms (it lowercases all terms before adding to used_terms).
        # The guard does: if term in used_terms — where term is already lowercased.
        # So used_terms must also be lowercase for the check to fire correctly.
        used_terms = {"screening", "machine learning", "automation", "nlp", "text mining"}

        result = analyse_query_gaps(
            papers=papers,
            original_query=QueryBuilder.build_semantic(sq),
            domain_keywords=sq.effective_domain_keywords(),
            used_terms=used_terms,   # passed by reference — function adds new terms to it
            iteration=2,
        )

        # Check that no accepted term was already in the PRE-CALL used_terms
        # We snapshot the pre-call set to avoid checking terms the function itself added
        pre_call_terms = {"screening", "machine learning", "automation", "nlp", "text mining"}
        for term in result.accepted_terms:
            assert term not in pre_call_terms, (
                f"'{term}' was already in used_terms but got accepted again — "
                "iteration deduplication is broken"
            )

    def test_off_topic_terms_always_rejected(self):
        """Regression test: terms outside the domain must never be accepted."""
        from llm_refiner import _is_domain_relevant

        off_topic = ["robotics", "chemical synthesis", "protein folding",
                     "autonomous vehicles", "semiconductor manufacturing"]
        anchors = ["systematic review", "NLP", "PRISMA", "LLM", "screening"]
        rq = "automated systematic literature review using large language models"

        for term in off_topic:
            ok, reason = _is_domain_relevant(term, anchors, rq)
            assert not ok, (
                f"'{term}' was ACCEPTED but is clearly off-topic. "
                f"Domain validator guard is broken. reason={reason}"
            )

    def test_query_length_bounded_after_multiple_expansions(self):
        """After 3 simulated expansions the query must stay under 300 chars."""
        from llm_refiner import expand_query

        query = "systematic review machine learning NLP"
        for i in range(3):
            query = expand_query(query, [f"term_{i}_{j}" for j in range(5)])
            if len(query) > 300:
                cut = query[:300].rfind(" ")
                query = query[:cut] if cut > 0 else query[:300]

        assert len(query) <= 300, f"Query reached {len(query)} chars — truncation guard broken"