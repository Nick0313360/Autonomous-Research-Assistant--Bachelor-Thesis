"""
main.py — Pipeline Runner
=========================
Runs Module 1 (search) → Module 2 (screening) end to end.

Usage
-----
# Full pipeline: basic search → screening
python main.py

# Full pipeline: iterative AI search → screening
python main.py --ai

# Skip search, load saved papers from a previous run → screening only
python main.py --load outputs/papers.json

# Search only, save papers, skip screening
python main.py --search-only

# Override the research query
python main.py --ai --query "machine learning evidence synthesis automation"
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

# ── Module 1 ──────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "module1_search"))
from module1_search.literature_handler import run_basic_search, run_iterative_search

# ── Module 2 ──────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "module2_screening"))
from module2_screening.screening_agent import run_screening, DEFAULT_CRITERIA

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
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _save_json(data, filename: str) -> str:
    path = os.path.join(OUTPUTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info("Saved → %s", path)
    return path


def _print_banner(text: str):
    bar = "═" * 60
    print(f"\n{bar}")
    print(f"  {text}")
    print(f"{bar}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — RUN MODULE 1
# ══════════════════════════════════════════════════════════════════════════════

def step_search(query: str, ai_mode: bool) -> list[dict]:
    _print_banner(f"MODULE 1 — Literature Search  ({'AI refinement' if ai_mode else 'basic'})")

    if ai_mode:
        papers = run_iterative_search(query)
    else:
        papers = run_basic_search(query)

    log.info("Module 1 complete — %d unique papers found", len(papers))
    return papers


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — RUN MODULE 2
# ══════════════════════════════════════════════════════════════════════════════

def step_screening(papers: list[dict]) -> dict:
    _print_banner("MODULE 2 — Screening Agent (2A title/abstract → 2B full-text)")

    results = run_screening(papers, criteria=DEFAULT_CRITERIA)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# PRINT FINAL SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

def print_summary(papers: list[dict], screening: dict):
    ts = _timestamp()
    stats = screening["prisma_stats"]

    _print_banner("PIPELINE COMPLETE — PRISMA SUMMARY")

    print(f"""
  Records identified (Module 1)     : {stats['records_screened']}
  ─────────────────────────────────────────────────
  Excluded at title/abstract (2A)   : {stats['excluded_title_abstract']}
  Uncertain → human review queue    : {stats['uncertain_flagged_for_human']}
  Sent to full-text screening (2B)  : {stats['sent_to_fulltext']}
  ─────────────────────────────────────────────────
  No PDF available                  : {stats['no_pdf_available']}
  Excluded at full-text (2B)        : {stats['excluded_fulltext']}
  ─────────────────────────────────────────────────
  FINAL INCLUDED                    : {stats['final_included']}
""")

    if screening["included_papers"]:
        print("  INCLUDED PAPERS:")
        for p in screening["included_papers"]:
            print(f"    ✓  {p['title']}")

    if screening["uncertain"]:
        print(f"\n  UNCERTAIN — needs human review ({len(screening['uncertain'])} papers):")
        for u in screening["uncertain"]:
            print(f"    ?  {u['paper']['title']}")
            print(f"       reason: {u['reason']}")

    print()

    # save everything
    _save_json(papers,                          f"papers_{ts}.json")
    _save_json(screening["included_papers"],    f"included_{ts}.json")
    _save_json(screening["prisma_stats"],       f"prisma_stats_{ts}.json")
    _save_json(screening["decision_log"],       f"decision_log_{ts}.json")
    _save_json(screening["uncertain"],          f"uncertain_{ts}.json")

    print(f"  All outputs saved to → {OUTPUTS_DIR}/")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def parse_args():
    parser = argparse.ArgumentParser(
        description="SLR Agent — Module 1 + Module 2 pipeline"
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="Use iterative LLM query refinement in Module 1 (default: basic search)",
    )
    parser.add_argument(
        "--query",
        type=str,
        default="artificial intelligence systematic review automation",
        help="Initial search query (default: 'artificial intelligence systematic review automation')",
    )
    parser.add_argument(
        "--load",
        type=str,
        default=None,
        metavar="PATH",
        help="Skip Module 1 — load papers from a saved JSON file instead",
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="Run Module 1 only, save papers, skip screening",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ── STEP 1: get papers ────────────────────────────────────────────────────
    if args.load:
        # load from previous run
        log.info("Loading papers from %s", args.load)
        with open(args.load, encoding="utf-8") as f:
            papers = json.load(f)
        log.info("Loaded %d papers", len(papers))
    else:
        papers = step_search(args.query, ai_mode=args.ai)
        # always save raw search results so you can re-run screening without
        # hitting the APIs again
        _save_json(papers, f"papers_{_timestamp()}.json")

    if args.search_only:
        _print_banner(f"Search-only mode — {len(papers)} papers saved. Exiting.")
        return

    # ── STEP 2: screen ────────────────────────────────────────────────────────
    screening = step_screening(papers)

    # ── SUMMARY + SAVE ────────────────────────────────────────────────────────
    print_summary(papers, screening)


if __name__ == "__main__":
    main()