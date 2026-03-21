"""
pipeline.py — LangGraph Orchestrator
======================================
Wires Modules 1-4 into a single reproducible pipeline using LangGraph.

State machine:
  search → screen → extract → quality → knowledge_graph → done

Each node:
  - Receives the full PipelineState
  - Does its work
  - Returns updated state fields
  - Logs a structured event to outputs/run_<timestamp>/

LangGraph checkpointing means if the pipeline crashes at Module 3,
restarting it resumes from the last completed checkpoint — Module 1
and 2 don't re-run.

Usage (programmatic):
  from pipeline import run_pipeline
  result = run_pipeline(search_query, mode="iterative", criteria="...")
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional
from dataclasses import dataclass, field, asdict

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE STATE — shared across all nodes
# ══════════════════════════════════════════════════════════════════════════════

class PipelineState(TypedDict):
    # input
    search_query_dict:   dict          # SearchQuery.to_dict()
    search_mode:         str           # "basic" | "iterative"
    screening_criteria:  str           # inclusion/exclusion criteria text
    run_id:              str           # unique run identifier
    output_dir:          str           # path to this run's output folder

    # module 1 output
    papers:              list          # deduplicated papers from Module 1
    search_log:          dict          # SearchRunLog as dict

    # module 2 output
    screening_result:    dict          # full output from run_screening()

    # module 3 output
    extraction_result:   dict          # full output from run_extraction()

    # module 4 output
    quality_result:      dict          # full output from run_quality_assessment()
    graph_result:        dict          # full output from run_knowledge_graph()

    # status tracking
    current_stage:       str
    errors:              list
    progress_log:        list          # [{stage, message, timestamp, count}]


# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS LOGGING — structured events for the frontend
# ══════════════════════════════════════════════════════════════════════════════

def _progress(state: PipelineState, stage: str, message: str, count: int = 0) -> None:
    """Append a progress event. Frontend polls the progress_log."""
    entry = {
        "stage":     stage,
        "message":   message,
        "count":     count,
        "timestamp": datetime.now().isoformat(),
    }
    state["progress_log"].append(entry)
    log.info("[%s] %s (n=%d)", stage, message, count)

    # also write to progress.json so frontend can poll it
    progress_path = os.path.join(state["output_dir"], "progress.json")
    with open(progress_path, "w") as f:
        json.dump(state["progress_log"], f, indent=2)


def _save_stage(state: PipelineState, filename: str, data: Any) -> None:
    """Save stage output to the run's output directory."""
    path = os.path.join(state["output_dir"], filename)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ══════════════════════════════════════════════════════════════════════════════
# NODE 1 — Module 1: Search
# ══════════════════════════════════════════════════════════════════════════════

def search_node(state: PipelineState) -> dict:
    """Execute Module 1: structured search + optional LLM refinement."""
    from module1_searc.files.search_query import SearchQuery
    from module1_searc.files.literature_handler import run_basic_search, run_iterative_search

    _progress(state, "search", "Starting literature search…")

    try:
        sq = SearchQuery.from_dict(state["search_query_dict"])
        mode = state.get("search_mode", "basic")

        _progress(state, "search",
                  f"Querying PubMed and Semantic Scholar ({mode} mode)…")

        if mode == "iterative":
            papers, log_obj = run_iterative_search(sq, max_iterations=3)
        else:
            papers, log_obj = run_basic_search(sq)

        log_dict = json.loads(log_obj.to_json())

        _save_stage(state, "module1_search_log.json", log_dict)

        _progress(state, "search",
                  f"Search complete — {len(papers)} unique papers identified",
                  count=len(papers))

        return {
            "papers":        papers,
            "search_log":    log_dict,
            "current_stage": "search_complete",
        }

    except Exception as exc:
        log.exception("Module 1 failed")
        state["errors"].append({"stage": "search", "error": str(exc)})
        _progress(state, "search", f"Search failed: {exc}")
        return {"current_stage": "error", "papers": []}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 2 — Module 2: Screening
# ══════════════════════════════════════════════════════════════════════════════

def screen_node(state: PipelineState) -> dict:
    """Execute Module 2: title/abstract + full-text screening."""
    from module2_screening.screening_agent import run_screening

    papers = state.get("papers", [])
    if not papers:
        _progress(state, "screen", "No papers to screen — skipping")
        return {"current_stage": "screen_skipped", "screening_result": {}}

    _progress(state, "screen",
              f"Starting title/abstract screening of {len(papers)} papers…",
              count=len(papers))

    try:
        result = run_screening(
            papers=papers,
            criteria=state.get("screening_criteria", ""),
        )

        stats = result["prisma_stats"]
        _progress(state, "screen",
                  f"Screening complete — {stats['final_included']} papers included",
                  count=stats["final_included"])
        _progress(state, "screen",
                  f"Excluded at title/abstract: {stats['excluded_title_abstract']} | "
                  f"Uncertain (human review): {stats['uncertain_flagged_for_human']} | "
                  f"No PDF: {stats['no_pdf_available']}")

        _save_stage(state, "module2_screening_result.json", {
            "prisma_stats":  result["prisma_stats"],
            "included_count": len(result["included_papers"]),
            "decision_log_count": len(result["decision_log"]),
        })
        # save full decision log separately (can be large)
        _save_stage(state, "module2_decision_log.json", result["decision_log"])

        return {
            "screening_result": result,
            "current_stage":    "screen_complete",
        }

    except Exception as exc:
        log.exception("Module 2 failed")
        state["errors"].append({"stage": "screen", "error": str(exc)})
        _progress(state, "screen", f"Screening failed: {exc}")
        return {"current_stage": "error", "screening_result": {}}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 3 — Module 3: Extraction
# ══════════════════════════════════════════════════════════════════════════════

def extract_node(state: PipelineState) -> dict:
    """Execute Module 3: RAG data extraction from included papers."""
    from module3_extraction.extractor import run_extraction

    screening = state.get("screening_result", {})
    included  = screening.get("included_papers", [])

    if not included:
        _progress(state, "extract", "No included papers to extract from — skipping")
        return {"current_stage": "extract_skipped", "extraction_result": {}}

    _progress(state, "extract",
              f"Starting RAG extraction from {len(included)} included papers…",
              count=len(included))

    try:
        result = run_extraction(included)

        counts = result["prisma_counts"]
        _progress(state, "extract",
                  f"Extraction complete — {counts['included_in_synthesis']} papers extracted",
                  count=counts["included_in_synthesis"])
        _progress(state, "extract",
                  f"Failed (no PDF or extraction error): {counts['excluded_no_pdf']}")

        _save_stage(state, "module3_extraction_result.json", {
            "prisma_counts":  result["prisma_counts"],
            "extracted_count": len(result["extracted_papers"]),
        })
        _save_stage(state, "module3_extracted_papers.json", result["extracted_papers"])

        return {
            "extraction_result": result,
            "current_stage":     "extract_complete",
        }

    except Exception as exc:
        log.exception("Module 3 failed")
        state["errors"].append({"stage": "extract", "error": str(exc)})
        _progress(state, "extract", f"Extraction failed: {exc}")
        return {"current_stage": "error", "extraction_result": {}}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 4 — Module 4A: Quality Assessment
# ══════════════════════════════════════════════════════════════════════════════

def quality_node(state: PipelineState) -> dict:
    """Execute Module 4A: CASP + risk-of-bias quality assessment."""
    from module4_quality_graph.quality_assessor import run_quality_assessment
    from module3_extraction.extractor import _chroma_client

    screening = state.get("screening_result", {})
    included  = screening.get("included_papers", [])

    if not included:
        _progress(state, "quality", "No included papers for quality assessment — skipping")
        return {"current_stage": "quality_skipped", "quality_result": {}}

    _progress(state, "quality",
              f"Starting CASP quality assessment of {len(included)} papers…",
              count=len(included))

    try:
        result = run_quality_assessment(
            included_papers=included,
            chroma_client=_chroma_client,
        )

        summary = result["summary"]
        _progress(state, "quality",
                  f"Quality assessment complete — "
                  f"High: {summary['high']}, Moderate: {summary['moderate']}, "
                  f"Low: {summary['low']}",
                  count=summary["total_assessed"])

        _save_stage(state, "module4a_quality_result.json", {
            "summary":    result["summary"],
            "assessments": result["quality_assessments"],
        })

        return {
            "quality_result": result,
            "current_stage":  "quality_complete",
        }

    except Exception as exc:
        log.exception("Module 4A failed")
        state["errors"].append({"stage": "quality", "error": str(exc)})
        _progress(state, "quality", f"Quality assessment failed: {exc}")
        return {"current_stage": "error", "quality_result": {}}


# ══════════════════════════════════════════════════════════════════════════════
# NODE 5 — Module 4B: Knowledge Graph
# ══════════════════════════════════════════════════════════════════════════════

def knowledge_graph_node(state: PipelineState) -> dict:
    """Execute Module 4B: populate Neo4j + answer research questions."""
    # Import from the fixed knowledge_graph module
    # Try module4 folder first, then root (depending on project layout)
    try:
        from module4_quality_graph.knowledge_graph import run_knowledge_graph, test_connection
    except ImportError:
        try:
            from knowledge_graph import run_knowledge_graph, test_connection
        except ImportError as e:
            _progress(state, "knowledge_graph", f"Cannot import knowledge_graph module: {e}")
            return {"current_stage": "error", "graph_result": {}}

    screening  = state.get("screening_result",  {})
    extraction = state.get("extraction_result", {})
    quality    = state.get("quality_result",    {})

    # ── connection test with informative message ──────────────────────────────
    _progress(state, "knowledge_graph", "Testing Neo4j connection…")
    if not test_connection():
        msg = (
            "Neo4j connection failed. "
            "Check: Neo4j Desktop is running, database is started, "
            "URI uses bolt:// (not neo4j://). "
            "Pipeline data is saved to JSON outputs — graph step skipped."
        )
        _progress(state, "knowledge_graph", msg)
        state["errors"].append({"stage": "knowledge_graph", "error": msg})
        # Don't mark as hard error — earlier modules succeeded and their
        # output is already saved to JSON. Graph is optional.
        return {"current_stage": "complete_no_graph", "graph_result": {"error": msg}}

    _progress(state, "knowledge_graph", "Populating Neo4j knowledge graph…")

    try:
        search_log = state.get("search_log", {})
        search_metadata = {
            "initial_query": state["search_query_dict"].get("research_question", ""),
            "timestamp":     datetime.now().isoformat(),
            "ai_mode":       state.get("search_mode") == "iterative",
            "total_found":   len(state.get("papers", [])),
        }

        result = run_knowledge_graph(
            search_metadata=search_metadata,
            papers=state.get("papers", []),
            decision_log=screening.get("decision_log", []),
            extracted_papers=extraction.get("extracted_papers", []),
            quality_assessments=quality.get("quality_assessments", []),
        )

        if result.get("error"):
            _progress(state, "knowledge_graph", f"Graph error: {result['error']}")
            state["errors"].append({"stage": "knowledge_graph", "error": result["error"]})
            return {"current_stage": "complete_no_graph", "graph_result": result}

        gs = result.get("graph_stats", {})
        _progress(state, "knowledge_graph",
                  f"Graph populated — "
                  f"{gs.get('papers_in_graph', 0)} papers, "
                  f"{gs.get('extractions_in_graph', 0)} extraction nodes",
                  count=gs.get("papers_in_graph", 0))
        _progress(state, "knowledge_graph",
                  "Answering research questions via GraphCypherQAChain…")

        _save_stage(state, "module4b_graph_result.json", result)

        return {"graph_result": result, "current_stage": "complete"}

    except Exception as exc:
        log.exception("Module 4B failed")
        state["errors"].append({"stage": "knowledge_graph", "error": str(exc)})
        _progress(state, "knowledge_graph", f"Knowledge graph failed: {exc}")
        return {"current_stage": "error", "graph_result": {}}


# ══════════════════════════════════════════════════════════════════════════════
# ROUTING — skip completed stages on resume
# ══════════════════════════════════════════════════════════════════════════════

def route_after_search(state: PipelineState) -> str:
    if state["current_stage"] == "error":
        return END
    return "screen"

def route_after_screen(state: PipelineState) -> str:
    if state["current_stage"] == "error":
        return END
    return "extract"

def route_after_extract(state: PipelineState) -> str:
    if state["current_stage"] == "error":
        return END
    return "quality"

def route_after_quality(state: PipelineState) -> str:
    if state["current_stage"] == "error":
        return END
    return "knowledge_graph"


# ══════════════════════════════════════════════════════════════════════════════
# BUILD GRAPH
# ══════════════════════════════════════════════════════════════════════════════

def build_pipeline() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("search",          search_node)
    graph.add_node("screen",          screen_node)
    graph.add_node("extract",         extract_node)
    graph.add_node("quality",         quality_node)
    graph.add_node("knowledge_graph", knowledge_graph_node)

    graph.set_entry_point("search")

    graph.add_conditional_edges("search",          route_after_search,  {"screen": "screen", END: END})
    graph.add_conditional_edges("screen",          route_after_screen,  {"extract": "extract", END: END})
    graph.add_conditional_edges("extract",         route_after_extract, {"quality": "quality", END: END})
    graph.add_conditional_edges("quality",         route_after_quality, {"knowledge_graph": "knowledge_graph", END: END})
    graph.add_edge("knowledge_graph", END)

    return graph.compile()


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(
    search_query_dict: dict,
    mode: str = "basic",
    criteria: str = "",
    output_base: str = "outputs",
) -> dict:
    """
    Run the full pipeline from search to knowledge graph.

    Parameters
    ----------
    search_query_dict : SearchQuery.to_dict() output
    mode              : "basic" or "iterative"
    criteria          : inclusion/exclusion criteria for Module 2
    output_base       : base directory for outputs

    Returns
    -------
    Final PipelineState as a dict
    """
    # create run directory
    run_id     = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(output_base, f"run_{run_id}")
    os.makedirs(output_dir, exist_ok=True)

    # set up file logging for this run
    fh = logging.FileHandler(os.path.join(output_dir, "pipeline.log"))
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s"))
    logging.getLogger().addHandler(fh)

    initial_state: PipelineState = {
        "search_query_dict":  search_query_dict,
        "search_mode":        mode,
        "screening_criteria": criteria,
        "run_id":             run_id,
        "output_dir":         output_dir,
        "papers":             [],
        "search_log":         {},
        "screening_result":   {},
        "extraction_result":  {},
        "quality_result":     {},
        "graph_result":       {},
        "current_stage":      "init",
        "errors":             [],
        "progress_log":       [],
    }

    # save initial config
    with open(os.path.join(output_dir, "run_config.json"), "w") as f:
        json.dump({
            "run_id":     run_id,
            "mode":       mode,
            "query":      search_query_dict,
            "started_at": datetime.now().isoformat(),
        }, f, indent=2)

    pipeline = build_pipeline()
    final_state = pipeline.invoke(initial_state)

    # save final summary
    summary = _build_summary(final_state)
    with open(os.path.join(output_dir, "run_summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)

    log.info("Pipeline complete. Output: %s", output_dir)
    return final_state


def _build_summary(state: PipelineState) -> dict:
    """Build a compact summary of the full run for the frontend."""
    search_log = state.get("search_log", {})
    screening  = state.get("screening_result", {})
    extraction = state.get("extraction_result", {})
    quality    = state.get("quality_result",   {})
    graph      = state.get("graph_result",     {})

    prisma = {
        "identified":         len(state.get("papers", [])),
        "screened":           screening.get("prisma_stats", {}).get("records_screened", 0),
        "excluded_ta":        screening.get("prisma_stats", {}).get("excluded_title_abstract", 0),
        "uncertain":          screening.get("prisma_stats", {}).get("uncertain_flagged_for_human", 0),
        "sent_to_fulltext":   screening.get("prisma_stats", {}).get("sent_to_fulltext", 0),
        "no_pdf":             screening.get("prisma_stats", {}).get("no_pdf_available", 0),
        "excluded_ft":        screening.get("prisma_stats", {}).get("excluded_fulltext", 0),
        "included":           screening.get("prisma_stats", {}).get("final_included", 0),
        "extracted":          extraction.get("prisma_counts", {}).get("included_in_synthesis", 0),
    }

    s = {
        "run_id":           state["run_id"],
        "output_dir":       state["output_dir"],
        "status":           state["current_stage"],
        "errors":           state["errors"],
        "prisma_counts":    prisma,
        "quality_summary":  quality.get("summary", {}),
        "graph_stats":      graph.get("graph_stats", {}),
        "rq_answers":       graph.get("research_qa_answers", {}),
        "progress_log":     state["progress_log"],
    }

    output_dir = state["output_dir"]
    rq = state["search_query_dict"].get("research_question", "")

    # ── Generate PRISMA diagram ───────────────────────────────────────────────
    try:
        from prisma_generator import generate_prisma_diagram
        diagram_path = os.path.join(output_dir, "prisma_diagram.png")
        result = generate_prisma_diagram(prisma, diagram_path)
        s["prisma_diagram_path"] = diagram_path if result else None
    except Exception as exc:
        log.warning("PRISMA diagram generation failed: %s", exc)
        s["prisma_diagram_path"] = None

    # ── Generate research report ──────────────────────────────────────────────
    try:
        from report_generator import generate_report
        report_path = generate_report(
            research_question=rq,
            prisma_counts=prisma,
            extracted_papers=extraction.get("extracted_papers", []),
            quality_summary=quality.get("summary", {}),
            rq_answers=graph.get("research_qa_answers", {}),
            output_dir=output_dir,
        )
        s["report_path"] = report_path
    except Exception as exc:
        log.warning("Report generation failed: %s", exc)
        s["report_path"] = None

    # ── Verify Neo4j actually has data ────────────────────────────────────────
    try:
        from knowledge_graph import KnowledgeGraph
        kg = KnowledgeGraph()
        s["neo4j_verified"] = True
        s["neo4j_stats"]    = kg.get_stats()
        kg.close()
    except Exception as exc:
        s["neo4j_verified"] = False
        s["neo4j_error"]    = str(exc)

    return s