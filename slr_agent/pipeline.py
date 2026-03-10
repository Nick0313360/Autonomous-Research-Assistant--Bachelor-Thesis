"""
pipeline.py — Full SLR Agent Pipeline
======================================
Orchestrates Module 1 → Module 2 → Module 3 using LangGraph.

Module 1  : Literature search + iterative LLM query refinement
Module 2  : Two-stage screening (title/abstract → full-text)
Module 3  : RAG data extraction (ChromaDB + embeddings + LLM)

Usage
-----
python pipeline.py                          # basic search → screen → extract
python pipeline.py --ai                     # AI iterative search → screen → extract
python pipeline.py --ai --query "..."       # custom query
python pipeline.py --load outputs/papers_X.json   # skip search, use saved papers
python pipeline.py --search-only            # Module 1 only
python pipeline.py --screen-only --load X  # Module 2 only on saved papers

Install dependencies
--------------------
pip install langgraph pymupdf langchain-text-splitters chromadb pydantic pdfminer.six
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Optional

# ── LangGraph ─────────────────────────────────────────────────────────────────
from langgraph.graph import StateGraph, END
from typing import TypedDict

# ── Module 1 ──────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "module1_search"))
from module1_search.literature_handler import run_basic_search, run_iterative_search

# ── Module 2 ──────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "module2_screening"))
from module2_screening.screening_agent import run_screening, DEFAULT_CRITERIA

# ── Module 3 ──────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "module3_extraction"))
from module3_extraction.extractor import run_extraction

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

# ── output directory ──────────────────────────────────────────────────────────
OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# SHARED STATE SCHEMA
# This TypedDict is the single object that flows through every LangGraph node.
# Every module reads from it and writes back to it.
# Nothing is passed as function arguments between nodes — only state.
# ══════════════════════════════════════════════════════════════════════════════

class SLRState(TypedDict):
    # ── pipeline config (set once at start, never mutated) ───────────────────
    query:              str          # initial search query
    ai_mode:            bool         # True = iterative LLM refinement in M1
    criteria:           str          # inclusion/exclusion criteria for M2
    search_only:        bool         # stop after Module 1
    screen_only:        bool         # stop after Module 2

    # ── Module 1 outputs ─────────────────────────────────────────────────────
    papers:             list[dict]   # all unique papers found
    search_metadata:    dict         # query strings, timestamps, counts per iteration

    # ── Module 2 outputs ─────────────────────────────────────────────────────
    included_papers:    list[dict]   # papers that passed both 2A and 2B
    excluded_ta:        list[dict]   # excluded at title/abstract
    excluded_ft:        list[dict]   # excluded at full-text
    uncertain:          list[dict]   # flagged for human review
    no_pdf:             list[dict]   # passed 2A but no PDF found
    decision_log:       list[dict]   # full per-paper audit trail
    prisma_m2:          dict         # PRISMA counts from Module 2

    # ── Module 3 outputs ─────────────────────────────────────────────────────
    extracted_papers:   list[dict]   # ExtractedPaper dicts (validated by Pydantic)
    failed_extraction:  list[dict]   # papers where PDF/extraction failed
    prisma_m3:          dict         # PRISMA counts from Module 3

    # ── pipeline control ─────────────────────────────────────────────────────
    error:              Optional[str]   # set if any node crashes
    completed_stages:   list[str]       # audit trail of which nodes ran


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _ts() -> str:
    """Timestamp string for filenames."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _save(data, name: str) -> str:
    """Save data to outputs/ and return the path."""
    path = os.path.join(OUTPUTS_DIR, f"{name}_{_ts()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info("Saved → %s", path)
    return path


def _banner(text: str):
    bar = "═" * 62
    print(f"\n{bar}\n  {text}\n{bar}")


# ══════════════════════════════════════════════════════════════════════════════
# NODE 1 — SEARCH  (Module 1)
# ══════════════════════════════════════════════════════════════════════════════

def search_node(state: SLRState) -> SLRState:
    """
    Run Module 1: query PubMed (+ Semantic Scholar if key available),
    deduplicate results, optionally run iterative LLM query refinement.

    Writes to state:
      - papers            : flat list of unique paper dicts
      - search_metadata   : what queries ran, when, how many results
      - completed_stages  : appends "search"
    """
    _banner("MODULE 1 — Literature Search")

    try:
        if state["ai_mode"]:
            log.info("Running iterative AI search for: %s", state["query"])
            papers = run_iterative_search(state["query"])
        else:
            log.info("Running basic search for: %s", state["query"])
            papers = run_basic_search(state["query"])

        log.info("Module 1 complete — %d unique papers", len(papers))

        return {
            **state,
            "papers": papers,
            "search_metadata": {
                "initial_query": state["query"],
                "ai_mode":       state["ai_mode"],
                "timestamp":     datetime.now().isoformat(),
                "total_found":   len(papers),
            },
            "completed_stages": state["completed_stages"] + ["search"],
            "error": None,
        }

    except Exception as exc:
        log.error("search_node crashed: %s", exc)
        return {**state, "error": f"search_node: {exc}"}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2 — SCREENING  (Module 2)
# ══════════════════════════════════════════════════════════════════════════════

def screening_node(state: SLRState) -> SLRState:
    """
    Run Module 2:
      2A — title/abstract screening with LLM (include/exclude/uncertain)
      2B — full-text screening via Unpaywall PDF + LLM

    Reads from state  : papers, criteria
    Writes to state   : included_papers, excluded_ta, excluded_ft,
                        uncertain, no_pdf, decision_log, prisma_m2
    """
    _banner(f"MODULE 2 — Screening  ({len(state['papers'])} papers)")

    try:
        results = run_screening(
            papers=state["papers"],
            criteria=state["criteria"],
        )

        log.info(
            "Module 2 complete — included: %d | excluded_ta: %d | "
            "excluded_ft: %d | uncertain: %d",
            len(results["included_papers"]),
            len(results["excluded_title_abstract"]),
            len(results["excluded_fulltext"]),
            len(results["uncertain"]),
        )

        return {
            **state,
            "included_papers":  results["included_papers"],
            "excluded_ta":      results["excluded_title_abstract"],
            "excluded_ft":      results["excluded_fulltext"],
            "uncertain":        results["uncertain"],
            "no_pdf":           results["no_pdf"],
            "decision_log":     results["decision_log"],
            "prisma_m2":        results["prisma_stats"],
            "completed_stages": state["completed_stages"] + ["screening"],
            "error":            None,
        }

    except Exception as exc:
        log.error("screening_node crashed: %s", exc)
        return {**state, "error": f"screening_node: {exc}"}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 3 — EXTRACTION  (Module 3 — RAG)
# ══════════════════════════════════════════════════════════════════════════════

def extraction_node(state: SLRState) -> SLRState:
    """
    Run Module 3: RAG-based structured data extraction.

    For each included paper:
      Layer 1 — download PDF, extract text page by page (PyMuPDF)
      Layer 2 — chunk text, embed with embeddinggemma:300m, store in ChromaDB
      Layer 3 — for each field: embed query → retrieve top-4 chunks → LLM extracts
      Layer 4 — validate result with Pydantic ExtractedPaper schema

    Reads from state  : included_papers
    Writes to state   : extracted_papers, failed_extraction, prisma_m3
    """
    _banner(f"MODULE 3 — RAG Extraction  ({len(state['included_papers'])} papers)")

    try:
        results = run_extraction(state["included_papers"])

        log.info(
            "Module 3 complete — extracted: %d | failed: %d",
            len(results["extracted_papers"]),
            len(results["failed_papers"]),
        )

        return {
            **state,
            "extracted_papers":  results["extracted_papers"],
            "failed_extraction": results["failed_papers"],
            "prisma_m3":         results["prisma_counts"],
            "completed_stages":  state["completed_stages"] + ["extraction"],
            "error":             None,
        }

    except Exception as exc:
        log.error("extraction_node crashed: %s", exc)
        return {**state, "error": f"extraction_node: {exc}"}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 4 — SAVE  (always runs last)
# ══════════════════════════════════════════════════════════════════════════════

def save_node(state: SLRState) -> SLRState:
    """
    Persist all pipeline outputs to outputs/ directory.
    Runs after every terminal stage regardless of which modules ran.

    Saves:
      papers.json          — all papers from Module 1
      included.json        — papers that passed Module 2
      decision_log.json    — full screening audit trail
      uncertain.json       — papers flagged for human review
      prisma_stats.json    — combined PRISMA counts from M1 + M2 + M3
      extracted.json       — structured extraction results from Module 3
    """
    _banner("SAVING OUTPUTS")

    # always save what we have, even if pipeline stopped early
    if state.get("papers"):
        _save(state["papers"], "papers")

    if state.get("included_papers"):
        _save(state["included_papers"], "included")

    if state.get("decision_log"):
        _save(state["decision_log"], "decision_log")

    if state.get("uncertain"):
        _save(state["uncertain"], "uncertain")

    if state.get("extracted_papers"):
        _save(state["extracted_papers"], "extracted")

    if state.get("failed_extraction"):
        _save(state["failed_extraction"], "failed_extraction")

    # combine PRISMA stats from all modules into one report
    combined_prisma = {
        "module1": {
            "total_identified": len(state.get("papers", [])),
            "query":            state.get("search_metadata", {}).get("initial_query"),
        },
        "module2": state.get("prisma_m2", {}),
        "module3": state.get("prisma_m3", {}),
        "stages_completed": state.get("completed_stages", []),
    }
    _save(combined_prisma, "prisma_stats")

    return {**state, "completed_stages": state["completed_stages"] + ["save"]}


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING FUNCTIONS  (conditional edges in the graph)
# ══════════════════════════════════════════════════════════════════════════════

def after_search(state: SLRState) -> str:
    """
    After Module 1: decide what to do next.
    - Error or no papers → save what we have and end
    - search_only flag   → save and end
    - Otherwise          → proceed to screening
    """
    if state.get("error"):
        log.error("Stopping after search — error: %s", state["error"])
        return "save"
    if not state.get("papers"):
        log.warning("Stopping after search — no papers found")
        return "save"
    if state.get("search_only"):
        log.info("search_only mode — stopping after Module 1")
        return "save"
    return "screen"


def after_screening(state: SLRState) -> str:
    """
    After Module 2: decide what to do next.
    - Error               → save and end
    - screen_only flag    → save and end
    - No papers included  → save (nothing to extract)
    - Otherwise           → proceed to extraction
    """
    if state.get("error"):
        log.error("Stopping after screening — error: %s", state["error"])
        return "save"
    if state.get("screen_only"):
        log.info("screen_only mode — stopping after Module 2")
        return "save"
    if not state.get("included_papers"):
        log.warning("No papers passed screening — skipping extraction")
        return "save"
    return "extract"


def after_extraction(state: SLRState) -> str:
    """After Module 3 — always save."""
    return "save"


# ══════════════════════════════════════════════════════════════════════════════
# BUILD THE GRAPH
# ══════════════════════════════════════════════════════════════════════════════

def build_graph():
    """
    Construct and compile the LangGraph state machine.

    Graph structure:
      START → search → [screen | save → END]
                          ↓
                       screen → [extract | save → END]
                                    ↓
                                 extract → save → END

    Conditional edges make the routing decisions based on state contents.
    """
    graph = StateGraph(SLRState)

    # register all nodes
    graph.add_node("search",   search_node)
    graph.add_node("screen",   screening_node)
    graph.add_node("extract",  extraction_node)
    graph.add_node("save",     save_node)

    # entry point
    graph.set_entry_point("search")

    # conditional edge: after search → screen OR save
    graph.add_conditional_edges(
        "search",
        after_search,
        {
            "screen": "screen",
            "save":   "save",
        }
    )

    # conditional edge: after screening → extract OR save
    graph.add_conditional_edges(
        "screen",
        after_screening,
        {
            "extract": "extract",
            "save":    "save",
        }
    )

    # conditional edge: after extraction → always save
    graph.add_conditional_edges(
        "extract",
        after_extraction,
        {
            "save": "save",
        }
    )

    # save always ends the pipeline
    graph.add_edge("save", END)

    return graph.compile()


# ══════════════════════════════════════════════════════════════════════════════
# PRINT FINAL SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(state: SLRState):
    """Print a human-readable PRISMA summary after the pipeline finishes."""
    _banner("PIPELINE COMPLETE — PRISMA SUMMARY")

    m2 = state.get("prisma_m2") or {}
    m3 = state.get("prisma_m3") or {}

    print(f"""
  ── MODULE 1 — Identification ──────────────────────────────
  Records identified                : {len(state.get('papers', []))}

  ── MODULE 2 — Screening ───────────────────────────────────
  Records screened (title/abstract) : {m2.get('records_screened', 0)}
  Excluded at title/abstract        : {m2.get('excluded_title_abstract', 0)}
  Uncertain → human review          : {m2.get('uncertain_flagged_for_human', 0)}
  Sent to full-text screening       : {m2.get('sent_to_fulltext', 0)}
  No PDF available                  : {m2.get('no_pdf_available', 0)}
  Excluded at full-text             : {m2.get('excluded_fulltext', 0)}
  Passed screening (included)       : {m2.get('final_included', 0)}

  ── MODULE 3 — Extraction ──────────────────────────────────
  Attempted extraction              : {m3.get('total_attempted', 0)}
  Successfully extracted            : {m3.get('included_in_synthesis', 0)}
  Failed (no PDF / error)           : {m3.get('excluded_no_pdf', 0)}

  ── Stages completed ───────────────────────────────────────
  {' → '.join(state.get('completed_stages', []))}
""")

    # show extracted fields for included papers
    if state.get("extracted_papers"):
        print("  EXTRACTED PAPERS:")
        for p in state["extracted_papers"]:
            print(f"\n    ✓ {p['title'][:70]}")
            print(f"      Tool      : {p.get('tool_name')}")
            print(f"      LLM       : {p.get('llm_used')}")
            print(f"      Kappa     : {p.get('reported_kappa')}")
            print(f"      Sensitivity: {p.get('reported_sensitivity')}")
            print(f"      Sample n  : {p.get('sample_size')}")
            sourced = list(p.get("sources", {}).keys())
            print(f"      Sourced fields: {sourced}")

    if state.get("uncertain"):
        print(f"\n  UNCERTAIN — needs human review ({len(state['uncertain'])} papers):")
        for u in state["uncertain"]:
            print(f"    ? {u['paper']['title'][:70]}")

    print(f"\n  All outputs saved to → {OUTPUTS_DIR}/\n")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(description="SLR Agent — full pipeline")
    p.add_argument("--ai",           action="store_true")
    p.add_argument("--query",        type=str, default="artificial intelligence automation systematic review")
    p.add_argument("--load",         type=str, default=None, metavar="PATH")
    p.add_argument("--search-only",  action="store_true")
    p.add_argument("--screen-only",  action="store_true")
    p.add_argument("--extract-only", action="store_true")   # ← ADD THIS
    p.add_argument("--skip-graph",   action="store_true")   # ← ADD THIS
    p.add_argument("--criteria",     type=str, default=None)
    return p.parse_args()


def main():
    args = parse_args()

    # load custom criteria from file if provided
    criteria = DEFAULT_CRITERIA
    if args.criteria and os.path.exists(args.criteria):
        with open(args.criteria) as f:
            criteria = f.read()
        log.info("Loaded custom criteria from %s", args.criteria)

    # ── build initial state ───────────────────────────────────────────────────
    initial_state: SLRState = {
        "query":             args.query,
        "ai_mode":           args.ai,
        "criteria":          criteria,
        "search_only":       args.search_only,
        "screen_only":       args.screen_only,
        "papers":            [],
        "search_metadata":   {},
        "included_papers":   [],
        "excluded_ta":       [],
        "excluded_ft":       [],
        "uncertain":         [],
        "no_pdf":            [],
        "decision_log":      [],
        "prisma_m2":         {},
        "extracted_papers":  [],
        "failed_extraction": [],
        "prisma_m3":         {},
        "completed_stages":  [],
        "error":             None,
    }

    # ── if --load: skip Module 1, inject papers directly ─────────────────────
    if args.load:
        log.info("Loading papers from %s (skipping Module 1)", args.load)
        with open(args.load, encoding="utf-8") as f:
            loaded_papers = json.load(f)
        log.info("Loaded %d papers", len(loaded_papers))
        initial_state["papers"]           = loaded_papers
        initial_state["completed_stages"] = ["search"]
        # override the entry point by starting at screening
        # we do this by running the graph but skipping search via papers being pre-filled
        # LangGraph will still call search_node but it will detect papers already set
        # simpler: just call screening and extraction directly
        graph = build_graph()

        # inject pre-loaded papers and route past search
        # by calling the graph with papers already populated
        # LangGraph calls search_node first — we override it
        state_with_papers = {**initial_state}
        # manually run screen → extract → save since search is already done
        state_with_papers = screening_node(state_with_papers)
        if not args.screen_only and state_with_papers.get("included_papers"):
            state_with_papers = extraction_node(state_with_papers)
        final_state = save_node(state_with_papers)
        print_summary(final_state)
        return

    # ── normal run: let LangGraph orchestrate everything ─────────────────────
    graph = build_graph()
    final_state = graph.invoke(initial_state)
    print_summary(final_state)


if __name__ == "__main__":
    main()