"""
main.py — CLI Entry Point
==========================
Run the full pipeline from the command line.

Usage
-----
  # Interactive query builder + basic search:
  python main.py --interactive

  # JSON query file + iterative search:
  python main.py --query module1_searc/files/example_query.json --mode iterative

  # Quick test with built-in demo query:
  python main.py --demo

  # Start the web frontend:
  python main.py --frontend
"""

import argparse
import json
import logging
import os
import sys

# make all module folders importable
ROOT = os.path.dirname(os.path.abspath(__file__))
for sub in ["module1_searc/files", "module2_screening",
            "module3_extraction", "module4_quality_graph"]:
    sys.path.insert(0, os.path.join(ROOT, sub))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)

DEFAULT_CRITERIA = """
INCLUSION
- Paper presents an empirical evaluation of an AI/ML tool used in at least
  one stage of a systematic review or evidence-synthesis pipeline.
- Written in English.
- Published in or after 2018.

EXCLUSION
- Conference abstracts, posters, editorials, or opinion pieces with no
  empirical data.
- Papers where automation is only discussed theoretically.
- Duplicate publications.
"""

DEMO_QUERY = {
    "research_question": "How do AI agents and large language models automate systematic literature review?",
    "population": "systematic review, literature review, scoping review",
    "intervention": "large language model, LLM, GPT, AI agent, machine learning, NLP",
    "comparison": None,
    "outcome": "title screening, abstract screening, PRISMA flow, data extraction",
    "domain_keywords": ["systematic review", "NLP", "PRISMA", "LLM"],
    "year_range": None,
    "max_papers_per_db": 100,   # small for demo speed
}


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous Research Assistant — Bachelor Thesis Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--interactive", action="store_true",
                        help="Launch guided PICO query builder")
    parser.add_argument("--query",  type=str,
                        help="Path to SearchQuery JSON file")
    parser.add_argument("--mode",   type=str, default="basic",
                        choices=["basic", "iterative"],
                        help="Search mode (default: basic)")
    parser.add_argument("--criteria", type=str, default=None,
                        help="Path to inclusion/exclusion criteria text file")
    parser.add_argument("--demo",   action="store_true",
                        help="Run with built-in demo query (small, fast)")
    parser.add_argument("--frontend", action="store_true",
                        help="Start the web frontend (Flask)")
    parser.add_argument("--output", type=str, default="outputs",
                        help="Base output directory (default: outputs)")
    args = parser.parse_args()

    # ── frontend mode ─────────────────────────────────────────────────────────
    if args.frontend:
        from frontend.app import create_app
        app = create_app()
        print("\n🌐 Frontend running at http://localhost:5000\n")
        app.run(debug=False, port=5000)
        return

    # ── build search query ────────────────────────────────────────────────────
    if args.demo:
        search_query_dict = DEMO_QUERY
        print("\n📋 Using built-in demo query")
        print(f"   RQ: {DEMO_QUERY['research_question']}")

    elif args.interactive:
        from search_query import prompt_search_query
        sq = prompt_search_query()
        search_query_dict = sq.to_dict()

    elif args.query:
        with open(args.query) as f:
            raw = json.load(f)
        # strip _comment / _instructions keys if present
        search_query_dict = {k: v for k, v in raw.items()
                             if not k.startswith("_")}
        print(f"\n📋 Loaded query: {search_query_dict.get('research_question', '')[:80]}")

    else:
        parser.print_help()
        print("\n⚠️  No query specified. Use --demo, --interactive, or --query <file>")
        return

    # ── load criteria ─────────────────────────────────────────────────────────
    criteria = DEFAULT_CRITERIA
    if args.criteria:
        with open(args.criteria) as f:
            criteria = f.read()

    # ── run pipeline ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  AUTONOMOUS RESEARCH ASSISTANT — PIPELINE START")
    print(f"  Mode: {args.mode.upper()}")
    print(f"{'='*60}\n")

    from pipeline import run_pipeline

    final_state = run_pipeline(
        search_query_dict=search_query_dict,
        mode=args.mode,
        criteria=criteria,
        output_base=args.output,
    )

    # ── print summary ─────────────────────────────────────────────────────────
    _print_summary(final_state)


def _print_summary(state: dict):
    from pipeline import _build_summary
    s = _build_summary(state)

    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Run ID   : {s['run_id']}")
    print(f"  Output   : {s['output_dir']}")
    print(f"  Status   : {s['status']}")
    print(f"{'='*60}")

    print("\n  PRISMA FLOW")
    p = s["prisma_counts"]
    print(f"  Identified               : {p['identified']}")
    print(f"  Screened (title/abstract): {p['screened']}")
    print(f"    Excluded (TA)          : {p['excluded_ta']}")
    print(f"    Uncertain (human)      : {p['uncertain']}")
    print(f"  Sent to full-text        : {p['sent_to_fulltext']}")
    print(f"    No PDF available       : {p['no_pdf']}")
    print(f"    Excluded (full-text)   : {p['excluded_ft']}")
    print(f"  Included in synthesis    : {p['included']}")
    print(f"  Data extracted           : {p['extracted']}")

    qs = s.get("quality_summary", {})
    if qs:
        print("\n  QUALITY ASSESSMENT")
        print(f"  High quality    : {qs.get('high', 0)}")
        print(f"  Moderate quality: {qs.get('moderate', 0)}")
        print(f"  Low quality     : {qs.get('low', 0)}")
        print(f"  Avg score       : {qs.get('avg_overall_score', 0):.2f}")

    rq = s.get("rq_answers", {})
    if rq:
        print("\n  RESEARCH QUESTIONS")
        for q, a in rq.items():
            print(f"\n  Q: {q}")
            print(f"  A: {a.get('answer', '')[:200]}")

    if s.get("errors"):
        print("\n  ⚠️  ERRORS")
        for e in s["errors"]:
            print(f"  [{e['stage']}] {e['error']}")

    print(f"\n  📄 Full results saved to: {s['output_dir']}\n")


if __name__ == "__main__":
    main()