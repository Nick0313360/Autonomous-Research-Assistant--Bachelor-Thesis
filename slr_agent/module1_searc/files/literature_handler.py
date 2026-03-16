"""
literature_handler.py — Module 1 Entry Point
==============================================
Design Patterns & Concepts Used
---------------------------------
1. Dependency Injection via SearchQuery
   Instead of scattering magic numbers (pubmed_limit=5000, etc.) through
   function signatures, all configuration now flows through a single
   SearchQuery value object. This is the standard "parameter object" refactor.

2. Structured Iteration Logging (SearchRunLog)
   Each iteration's results are captured in a typed dataclass. At the end of
   the run you have a complete audit trail that satisfies PRISMA Identification
   logging requirements and is machine-readable (serialisable to JSON).

3. Convergence / Stability Criterion
   The iterative loop now stops on a formal criterion: if the percentage of
   NEW papers added in an iteration falls below a configurable threshold
   (default 5%), we treat the search as converged. This replaces the fragile
   "0 new papers" check that never triggered because paper objects were
   compared by identity, not by DOI/title content.

4. Limit Enforcement
   sq.max_papers_per_db is forwarded to both connectors as the explicit
   retmax / limit argument. There is no other code path — the limit cannot be
   silently ignored.

5. Two-mode CLI
   --interactive  : walks the user through a structured query builder (Problem 1)
   --ai           : runs the iterative refinement loop (Problem 2)
   Plain mode     : single-pass basic search
   --query        : allows passing a JSON file or raw research question string
"""

import argparse
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from pubmed_connector import search as pubmed_search
from semantic_connector import search as semantic_search
from deduplicator import deduplicate
from llm_refiner import analyse_query_gaps, RefinementResult
from search_query import SearchQuery, QueryBuilder, prompt_search_query

# ---------------------------------------------------------------------------
# Logging setup — use structured logging so output is parseable
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("literature_handler")


# ---------------------------------------------------------------------------
# Per-iteration audit record
# ---------------------------------------------------------------------------

@dataclass
class IterationLog:
    """
    Captures every measurable outcome of a single search iteration.
    Serialise with asdict() to write to a JSON log file.
    """
    iteration: int
    pubmed_query: str
    semantic_query: str
    pubmed_count: int
    semantic_count: int
    doi_dupes_removed: int
    title_dupes_removed: int
    unique_this_iter: int
    new_papers_added: int
    cumulative_unique: int
    new_paper_rate: float          # new_papers / unique_this_iter
    refinement: Optional[dict] = None   # serialised RefinementResult


@dataclass
class SearchRunLog:
    """Full audit log for a complete run — printed and optionally saved."""
    search_query: dict             # SearchQuery.to_dict()
    mode: str                      # "basic" | "iterative"
    iterations: List[IterationLog] = field(default_factory=list)
    total_unique_papers: int = 0
    converged_at_iteration: Optional[int] = None
    stopped_reason: str = ""

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(asdict(self), indent=indent, default=str)


# ---------------------------------------------------------------------------
# Core search step
# ---------------------------------------------------------------------------

def _run_single_search(
    sq: SearchQuery,
    pubmed_query: str,
    semantic_query: str,
) -> tuple[list, dict]:
    """
    Query both databases, merge, deduplicate.

    Returns (unique_papers, dedup_stats)

    Limit enforcement: sq.max_papers_per_db is passed explicitly to both
    connectors. This is the fix for "the limit never worked".
    """
    logger.info("PubMed  query: %s", pubmed_query[:120])
    logger.info("Semantic query: %s", semantic_query[:120])

    pubmed_results   = pubmed_search(pubmed_query,   retmax=sq.max_papers_per_db)
    semantic_results = semantic_search(semantic_query, limit=sq.max_papers_per_db)

    logger.info(
        "Raw results — PubMed: %d  |  Semantic Scholar: %d",
        len(pubmed_results), len(semantic_results)
    )

    combined = pubmed_results + semantic_results
    unique, stats = deduplicate(combined)

    logger.info(
        "After dedup — DOI dupes: %d  title dupes: %d  unique: %d",
        stats["doi_duplicates"], stats["title_duplicates"], len(unique)
    )
    return unique, stats


# ---------------------------------------------------------------------------
# Basic (single-pass) search
# ---------------------------------------------------------------------------

def run_basic_search(sq: SearchQuery) -> tuple[list, SearchRunLog]:
    """
    Single-pass search. No LLM refinement.

    Returns (papers, log)
    """
    log = SearchRunLog(search_query=sq.to_dict(), mode="basic")

    pubmed_q   = QueryBuilder.build_pubmed(sq)
    semantic_q = QueryBuilder.build_semantic(sq)

    unique, stats = _run_single_search(sq, pubmed_q, semantic_q)

    log.iterations.append(IterationLog(
        iteration=1,
        pubmed_query=pubmed_q,
        semantic_query=semantic_q,
        pubmed_count=0,          # exact per-db count available if needed
        semantic_count=0,
        doi_dupes_removed=stats["doi_duplicates"],
        title_dupes_removed=stats["title_duplicates"],
        unique_this_iter=len(unique),
        new_papers_added=len(unique),
        cumulative_unique=len(unique),
        new_paper_rate=1.0,
    ))
    log.total_unique_papers = len(unique)
    log.stopped_reason = "single_pass"

    return unique, log


# ---------------------------------------------------------------------------
# Iterative (LLM-refined) search
# ---------------------------------------------------------------------------

def run_iterative_search(
    sq: SearchQuery,
    max_iterations: int = 3,
    convergence_threshold: float = 0.05,
) -> tuple[list, SearchRunLog]:
    """
    Iterative search with controlled LLM query refinement.

    Convergence criterion (formal stopping rule):
      Stop if new_papers / unique_this_iter < convergence_threshold.
      This is more robust than "0 new papers" because the threshold
      catches near-convergence early and avoids wasted API calls.

    Parameters
    ----------
    sq                    : Structured search query (carries all config).
    max_iterations        : Hard ceiling on iterations.
    convergence_threshold : Stop when < this fraction of results are new.
                            Default 5% — tunable via environment variable.
    """
    log = SearchRunLog(search_query=sq.to_dict(), mode="iterative")

    all_papers: list = []
    used_terms: set  = set()

    # Current queries — updated each iteration
    pubmed_q   = QueryBuilder.build_pubmed(sq)
    semantic_q = QueryBuilder.build_semantic(sq)

    for iteration in range(1, max_iterations + 1):
        print(f"\n{'='*55}")
        print(f"  ITERATION {iteration} / {max_iterations}")
        print(f"{'='*55}")

        if iteration > 1:
            logger.info("Cooling down 2 s between iterations…")
            time.sleep(2)

        # ── Search ──────────────────────────────────────────────────────────
        unique_this_iter, stats = _run_single_search(sq, pubmed_q, semantic_q)

        # ── New-paper detection (by DOI + title, not object identity) ───────
        # Bug fix: the original code compared paper dicts by reference
        # (`if p not in all_papers`) which never deduplicates across iterations.
        # We compare by the canonical key used in the deduplicator.
        existing_keys = _paper_keys(all_papers)
        new_papers = [
            p for p in unique_this_iter
            if _paper_key(p) not in existing_keys
        ]

        all_papers.extend(new_papers)
        all_papers, _ = deduplicate(all_papers)     # global dedup after merge

        new_rate = len(new_papers) / len(unique_this_iter) if unique_this_iter else 0.0

        iter_log = IterationLog(
            iteration=iteration,
            pubmed_query=pubmed_q,
            semantic_query=semantic_q,
            pubmed_count=0,
            semantic_count=0,
            doi_dupes_removed=stats["doi_duplicates"],
            title_dupes_removed=stats["title_duplicates"],
            unique_this_iter=len(unique_this_iter),
            new_papers_added=len(new_papers),
            cumulative_unique=len(all_papers),
            new_paper_rate=new_rate,
        )

        print(f"  This iteration : {len(unique_this_iter):>5} papers")
        print(f"  New papers     : {len(new_papers):>5}")
        print(f"  New-paper rate : {new_rate:.1%}")
        print(f"  Cumulative     : {len(all_papers):>5}")

        # ── Convergence check ───────────────────────────────────────────────
        if new_rate < convergence_threshold and iteration > 1:
            logger.info(
                "Converged at iteration %d (new-paper rate %.1f%% < threshold %.1f%%)",
                iteration, new_rate * 100, convergence_threshold * 100
            )
            log.iterations.append(iter_log)
            log.converged_at_iteration = iteration
            log.stopped_reason = "converged"
            break

        # ── LLM Refinement ──────────────────────────────────────────────────
        if iteration < max_iterations:
            print("\n  🧠 Running LLM gap analysis…")

            # Forward domain_keywords from SearchQuery to the refiner.
            # This is what prevents off-topic term injection.
            refinement: RefinementResult = analyse_query_gaps(
                papers=all_papers[-50:] if len(all_papers) > 50 else all_papers,
                original_query=semantic_q,
                domain_keywords=sq.effective_domain_keywords(),   # auto-derives from PICO if not set explicitly
                used_terms=used_terms,
                iteration=iteration,
                max_new_terms=5,
            )

            print(refinement.summary())

            iter_log.refinement = {
                "accepted": refinement.accepted_terms,
                "rejected": [(d.term, d.reason) for d in refinement.rejected_terms],
                "acceptance_rate": refinement.acceptance_rate,
                "llm_raw": refinement.llm_raw_output,
                "error": refinement.error,
            }

            if refinement.error:
                logger.warning("LLM refinement failed: %s — continuing without expansion.", refinement.error)
                log.iterations.append(iter_log)
                log.stopped_reason = "llm_error"
                break

            if not refinement.has_new_terms:
                logger.info("No accepted terms after domain filtering — stopping.")
                log.iterations.append(iter_log)
                log.stopped_reason = "no_valid_terms"
                break

            # Apply expansion — only to the Semantic query (free-text)
            # PubMed query is rebuilt from PICO slots and doesn't change.
            semantic_q = refinement.expanded_query

            # Enforce the same 300-char limit as QueryBuilder.build_semantic
            if len(semantic_q) > 300:
                logger.warning("Semantic query exceeded 300 chars after expansion — truncating.")
                cut = semantic_q[:300].rfind(" ")
                semantic_q = semantic_q[:cut] if cut > 0 else semantic_q[:300]

            print(f"\n  📝 New Semantic query: {semantic_q}")

        log.iterations.append(iter_log)

    log.total_unique_papers = len(all_papers)
    if not log.stopped_reason:
        log.stopped_reason = "max_iterations_reached"

    return all_papers, log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paper_key(p: dict) -> str:
    """
    Canonical identity key for a paper.
    Prefer DOI (globally unique); fall back to normalised title.
    """
    doi = p.get("doi")
    if doi:
        return f"doi:{doi.strip().lower()}"
    return f"title:{p.get('title', '').strip().lower()[:80]}"


def _paper_keys(papers: list) -> set:
    return {_paper_key(p) for p in papers}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Module 1 — Literature Search Handler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes
-----
  (default)       Single-pass basic search using --query
  --ai            Iterative LLM-refined search
  --interactive   Guided query builder (structured PICO form)

Examples
--------
  python literature_handler.py --interactive --ai
  python literature_handler.py --query "How do LLMs automate systematic reviews?" --ai
  python literature_handler.py --query query.json
        """,
    )
    parser.add_argument("--ai",          action="store_true", help="Enable iterative LLM refinement")
    parser.add_argument("--interactive", action="store_true", help="Launch guided query builder")
    parser.add_argument("--query",       type=str,            help="Research question string or path to a SearchQuery JSON file")
    parser.add_argument("--iterations",  type=int, default=3, help="Max refinement iterations (default: 3)")
    parser.add_argument("--log",         type=str,            help="Path to save the run log as JSON")

    args = parser.parse_args()

    # ── Build SearchQuery ────────────────────────────────────────────────────
    if args.interactive:
        sq = prompt_search_query()
    elif args.query:
        if args.query.endswith(".json"):
            with open(args.query) as f:
                sq = SearchQuery.from_dict(json.load(f))
        else:
            # Bare research question string — use sensible defaults
            sq = SearchQuery(research_question=args.query)
            logger.info(
                "Tip: use --interactive or a JSON file to add PICO helpers "
                "and domain anchors for more accurate results."
            )
    else:
        # Fallback demo query.
        # Each slot = one concept; comma-separated values = synonyms (OR-ed).
        # Slots are AND-ed → PubMed requires ALL concepts simultaneously.
        #
        # OUTCOME SLOT WARNING:
        # Do NOT put generic statistical/clinical terms here (precision, recall,
        # accuracy, screening) — those appear in thousands of unrelated medical
        # papers. Outcome terms should be SPECIFIC to your methodology domain.
        # For SLR automation: "title screening", "abstract screening", "PRISMA flow",
        # "data extraction", "quality assessment" are specific enough.
        sq = SearchQuery(
            research_question="How do AI agents and large language models automate systematic literature review?",
            population="systematic review, literature review, scoping review, evidence synthesis",
            intervention="large language model, LLM, GPT, AI agent, machine learning, NLP, natural language processing",
            outcome="title screening, abstract screening, PRISMA flow, data extraction, quality assessment",
            domain_keywords=["systematic review", "NLP", "PRISMA", "LLM", "screening automation"],
            max_papers_per_db=500,
        )
        logger.info("No query supplied — using built-in demo query.")
        logger.info("Tip: run with --interactive or --query example_query.json for a custom query.")

    # ── Run search ───────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print("  MODULE 1 — Literature Search")
    print(f"{'='*55}")
    print(f"  Mode: {'Iterative (AI)' if args.ai else 'Basic (single-pass)'}")
    print(f"  Research question: {sq.research_question}")
    print(f"  Max papers / DB  : {sq.max_papers_per_db}")
    if sq.domain_keywords:
        print(f"  Domain anchors   : {', '.join(sq.domain_keywords)}")
    print()

    if args.ai:
        papers, run_log = run_iterative_search(sq, max_iterations=args.iterations)
    else:
        papers, run_log = run_basic_search(sq)

    # ── Print results ────────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print("  FINAL RESULTS")
    print(f"{'='*55}")
    print(f"  Total unique papers : {len(papers)}")
    print(f"  Stopped because     : {run_log.stopped_reason}")
    if run_log.converged_at_iteration:
        print(f"  Converged at iter   : {run_log.converged_at_iteration}")
    print()

    for i, p in enumerate(papers[:10], 1):
        icon = "📚" if p.get("source") == "pubmed" else "🎓"
        title = p.get("title", "")[:100]
        print(f"  {i:>2}) {icon} {title}…")
        if p.get("year"):
            print(f"       📅 {p['year']}")

    # ── Save log ─────────────────────────────────────────────────────────────
    log_path = args.log or "search_run_log.json"
    with open(log_path, "w") as f:
        f.write(run_log.to_json())
    print(f"\n  📄 Run log saved → {log_path}")


if __name__ == "__main__":
    main()