"""
frontend/app.py — Flask Backend
=================================
Routes:
  GET  /              → query form
  POST /run           → starts pipeline in background thread, returns run_id
  GET  /stream/<id>   → SSE stream of progress.json updates
  GET  /result/<id>   → final result JSON
  GET  /status/<id>   → current stage + progress count
"""

import json
import os
import sys
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for sub in ["module1_searc/files", "module2_screening",
            "module3_extraction", "module4_quality_graph"]:
    sys.path.insert(0, os.path.join(ROOT, sub))

# active runs: run_id → {"state": ..., "done": bool, "output_dir": str}
_RUNS: dict = {}
_RUNS_LOCK = threading.Lock()

DEFAULT_CRITERIA = """
INCLUSION
- Paper presents an empirical evaluation of an AI/ML tool used in at least
  one stage of a systematic review or evidence-synthesis pipeline.
- Written in English.
- Published in or after 2018.

EXCLUSION
- Conference abstracts, posters, editorials, or opinion pieces with no empirical data.
- Papers where automation is only discussed theoretically.
- Duplicate publications.
"""


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ── index — query form ────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("index.html")

    # ── start pipeline ────────────────────────────────────────────────────────
    @app.route("/run", methods=["POST"])
    def start_run():
        data = request.json or {}

        # build SearchQuery dict from form fields
        sq_dict = {
            "research_question": data.get("research_question", "").strip(),
            "population":        data.get("population")   or None,
            "intervention":      data.get("intervention") or None,
            "comparison":        data.get("comparison")   or None,
            "outcome":           data.get("outcome")      or None,
            "domain_keywords":   [k.strip() for k in
                                  data.get("domain_keywords", "").split(",")
                                  if k.strip()],
            "year_range":        None,
            "max_papers_per_db": int(data.get("max_papers_per_db", 200)),
        }

        if yr := data.get("year_range", "").strip():
            try:
                parts = yr.split("-")
                sq_dict["year_range"] = [int(parts[0]), int(parts[1])]
            except Exception:
                pass

        mode     = data.get("mode", "basic")
        criteria = data.get("criteria", "").strip() or DEFAULT_CRITERIA

        if not sq_dict["research_question"]:
            return jsonify({"error": "research_question is required"}), 400

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(ROOT, "outputs", f"run_{run_id}")
        os.makedirs(output_dir, exist_ok=True)

        with _RUNS_LOCK:
            _RUNS[run_id] = {"done": False, "output_dir": output_dir, "state": None}

        # run pipeline in background thread
        def _run():
            try:
                from pipeline import run_pipeline
                state = run_pipeline(
                    search_query_dict=sq_dict,
                    mode=mode,
                    criteria=criteria,
                    output_base=os.path.join(ROOT, "outputs"),
                )
                with _RUNS_LOCK:
                    _RUNS[run_id]["state"] = state
                    _RUNS[run_id]["done"]  = True
            except Exception as exc:
                with _RUNS_LOCK:
                    _RUNS[run_id]["done"]  = True
                    _RUNS[run_id]["error"] = str(exc)

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        return jsonify({"run_id": run_id})

    # ── SSE progress stream ───────────────────────────────────────────────────
    @app.route("/stream/<run_id>")
    def stream(run_id):
        """
        Server-Sent Events stream.
        Polls progress.json every second and pushes new events to the browser.
        The browser's EventSource reconnects automatically on disconnect.
        """
        def generate():
            sent = 0
            output_dir = None

            with _RUNS_LOCK:
                run = _RUNS.get(run_id)
                if run:
                    output_dir = run["output_dir"]

            if not output_dir:
                yield f"data: {json.dumps({'error': 'Run not found'})}\n\n"
                return

            progress_file = os.path.join(output_dir, "progress.json")

            while True:
                # read progress file
                if os.path.exists(progress_file):
                    try:
                        with open(progress_file) as f:
                            events = json.load(f)
                    except Exception:
                        events = []

                    # send only new events
                    for event in events[sent:]:
                        yield f"data: {json.dumps(event)}\n\n"
                    sent = len(events)

                # check if done
                with _RUNS_LOCK:
                    done = _RUNS.get(run_id, {}).get("done", False)

                if done:
                    # send final summary
                    summary_file = os.path.join(output_dir, "run_summary.json")
                    if os.path.exists(summary_file):
                        with open(summary_file) as f:
                            summary = json.load(f)
                        yield f"data: {json.dumps({'type': 'complete', 'summary': summary})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'complete'})}\n\n"
                    return

                time.sleep(1.0)

        return Response(stream_with_context(generate()),
                        mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

    # ── result endpoint ───────────────────────────────────────────────────────
    @app.route("/result/<run_id>")
    def result(run_id):
        output_dir = os.path.join(ROOT, "outputs", f"run_{run_id}")
        summary_file = os.path.join(output_dir, "run_summary.json")
        if not os.path.exists(summary_file):
            return jsonify({"error": "Run not found or not complete"}), 404
        with open(summary_file) as f:
            return jsonify(json.load(f))

    # ── PRISMA diagram download ───────────────────────────────────────────────
    @app.route("/diagram/<run_id>")
    def diagram(run_id):
        path = os.path.join(ROOT, "outputs", f"run_{run_id}", "prisma_diagram.png")
        if not os.path.exists(path):
            return "PRISMA diagram not found", 404
        from flask import send_file
        return send_file(path, mimetype="image/png")

    # ── Research report download ──────────────────────────────────────────────
    @app.route("/report/<run_id>")
    def report(run_id):
        path = os.path.join(ROOT, "outputs", f"run_{run_id}", "research_report.md")
        if not os.path.exists(path):
            return "Research report not found", 404
        from flask import send_file
        return send_file(path, mimetype="text/markdown",
                         as_attachment=True, download_name="research_report.md")

    # ── preview query builder output ─────────────────────────────────────────
    @app.route("/preview_query", methods=["POST"])
    def preview_query():
        """Return the generated PubMed and S2 queries for user review."""
        from search_query import SearchQuery, QueryBuilder
        data = request.json or {}
        try:
            sq = SearchQuery(
                research_question=data.get("research_question", "").strip(),
                population=data.get("population")   or None,
                intervention=data.get("intervention") or None,
                comparison=data.get("comparison")   or None,
                outcome=data.get("outcome")         or None,
                domain_keywords=[k.strip() for k in
                                  data.get("domain_keywords", "").split(",")
                                  if k.strip()],
                max_papers_per_db=int(data.get("max_papers_per_db", 200)),
            )
            return jsonify({
                "pubmed_query":   QueryBuilder.build_pubmed(sq),
                "semantic_query": QueryBuilder.build_semantic(sq),
                "domain_keywords": sq.effective_domain_keywords(),
            })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    return app