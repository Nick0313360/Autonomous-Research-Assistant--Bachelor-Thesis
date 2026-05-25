"""FastAPI server for the Autonomous Systematic Review System."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CERT_DIR = Path("artefacts/cascade_rc/certificates")

_TOPIC_IDS = ["CD008874", "CD011145", "CD011768", "CD011975", "CD012080", "CD012768"]


# ---------------------------------------------------------------------------
# Module-level data setup
# ---------------------------------------------------------------------------

def _load_benchmark_topics() -> Dict[str, Dict[str, Any]]:
    topics: Dict[str, Dict[str, Any]] = {}
    for topic_id in _TOPIC_IDS:
        proto_path = Path(f"data/protocols/{topic_id}_benchmark.json")
        with proto_path.open(encoding="utf-8") as fh:
            raw = json.load(fh)

        bm = raw.get("benchmark", {})

        has_cert = (CERT_DIR / f"{topic_id}.pkl").exists()
        logger.info("Topic %s: cert=%s", topic_id, has_cert)

        topics[topic_id] = {
            "id":                   topic_id,
            "title":                raw["title"],
            "pico":                 raw["pico"],
            "qrels_path":           bm.get("qrels_path", ""),
            "canonical_pmids_path": bm.get("canonical_pmids_path", ""),
        }
    return topics


def _read_benchmark_eval(topic_id: str) -> Optional[Dict[str, Any]]:
    stats_path = Path(f"data/reports/{topic_id}_final_v1/run_stats.json")
    if not stats_path.exists():
        return None
    with stats_path.open(encoding="utf-8") as fh:
        return json.load(fh).get("benchmark_eval")


BENCHMARK_TOPICS: Dict[str, Dict[str, Any]] = _load_benchmark_topics()

# ---------------------------------------------------------------------------
# In-memory run registry
# ---------------------------------------------------------------------------

RUNS: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------------
# App + static dir (must exist before StaticFiles mount)
# ---------------------------------------------------------------------------

Path("frontend/static").mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Autonomous Systematic Review System")

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    pico: Dict[str, str]
    research_question: str
    max_papers: int = 100
    use_cascade_rc: bool = False
    benchmark_topic_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Startup hook
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def _startup() -> None:
    logger.info(
        "Server ready. %d topics loaded, %d with precomputed results, %d with certs.",
        len(BENCHMARK_TOPICS),
        sum(1 for tid in _TOPIC_IDS if _read_benchmark_eval(tid) is not None),
        sum(1 for tid in _TOPIC_IDS if (CERT_DIR / f"{tid}.pkl").exists()),
    )


# ---------------------------------------------------------------------------
# Endpoint 1: GET /api/topics
# ---------------------------------------------------------------------------


@app.get("/api/topics")
async def get_topics() -> List[Dict[str, Any]]:
    def _build() -> List[Dict[str, Any]]:
        return [
            {
                "id":              info["id"],
                "title":           info["title"],
                "pico":            info["pico"],
                "has_certificate": (CERT_DIR / f"{tid}.pkl").exists(),
                "benchmark_eval":  _read_benchmark_eval(tid),
            }
            for tid, info in BENCHMARK_TOPICS.items()
        ]

    return await asyncio.to_thread(_build)


# ---------------------------------------------------------------------------
# Endpoint 2: POST /api/runs
# ---------------------------------------------------------------------------


@app.post("/api/runs")
async def create_run(req: RunRequest) -> Dict[str, str]:
    if req.use_cascade_rc and not req.benchmark_topic_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cascade-RC requires a benchmark topic. "
                "Custom PICO cannot use conformal certificates."
            ),
        )
    if req.use_cascade_rc and not (CERT_DIR / f"{req.benchmark_topic_id}.pkl").exists():
        raise HTTPException(
            status_code=400,
            detail=f"No certificate found for {req.benchmark_topic_id}.",
        )

    run_id        = uuid.uuid4().hex[:8]
    output_dir    = Path("data/reports")
    protocol_path = Path(f"data/protocols/demo_{run_id}.json")

    protocol_json: Dict[str, Any] = {
        "title":               req.research_question[:80],
        "research_question":   req.research_question,
        "pico":                req.pico,
        "inclusion_criteria":  [
            {
                "criterion_id": "IC-01",
                "text":         "Studies relevant to the research question",
                "type":         "MANDATORY",
            }
        ],
        "exclusion_criteria":  [
            {
                "criterion_id": "EC-01",
                "text":         "Studies not relevant to the research question",
                "type":         "MANDATORY",
            }
        ],
        "target_databases":     ["pubmed", "semantic_scholar"],
        "max_papers_per_db":    req.max_papers,
        "date_range":           [2000, 2025],
        "language_restrictions": ["en"],
    }

    if req.benchmark_topic_id and req.benchmark_topic_id in BENCHMARK_TOPICS:
        bm_info = BENCHMARK_TOPICS[req.benchmark_topic_id]
        protocol_json["benchmark"] = {
            "topic_id":             req.benchmark_topic_id,
            "qrels_path":           bm_info["qrels_path"],
            "canonical_pmids_path": bm_info["canonical_pmids_path"],
        }

    await asyncio.to_thread(
        protocol_path.write_text,
        json.dumps(protocol_json, indent=2),
        "utf-8",
    )

    cmd = [
        "python", "main.py", str(protocol_path),
        "--review-id", f"demo_{run_id}",
        "--output-dir", str(output_dir),
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    run_dir = output_dir / f"demo_{run_id}"
    RUNS[run_id] = {
        "process":  process,
        "log_path": run_dir / "events.jsonl",
        "run_dir":  run_dir,
    }
    logger.info("Run %s started (pid=%s)", run_id, process.pid)
    return {"run_id": run_id}


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(t: str, stage: str = "", message: str = "", data: Any = None) -> str:
    payload: Dict[str, Any] = {"type": t, "stage": stage, "message": message}
    if data is not None:
        payload["data"] = data
    return f"data: {json.dumps(payload)}\n\n"


async def _sse_generator(run_id: str) -> AsyncGenerator[str, None]:
    run      = RUNS[run_id]
    process  = run["process"]
    log_path: Path = run["log_path"]

    # Wait up to 30 s for events.jsonl to appear
    deadline = time.monotonic() + 30.0
    while not log_path.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.5)

    if not log_path.exists():
        yield _sse("error", message="Pipeline did not start (events.jsonl not created)")
        return

    screening_counter = 0
    done_seen         = False
    last_growth_time  = time.monotonic()
    last_file_size    = -1          # -1 forces an update on first check
    last_proc_check   = time.monotonic()

    fh = await asyncio.to_thread(open, log_path, encoding="utf-8")
    try:
        while True:
            line: str = await asyncio.to_thread(fh.readline)

            if line:
                last_growth_time = time.monotonic()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "search.query_executed":
                    yield _sse(
                        "progress", "search",
                        f"Querying {event.get('database', 'PubMed')} — "
                        f"{event.get('n_results', 0)} records returned",
                    )

                elif etype == "pipeline.stage_complete":
                    stage_val = event.get("stage", "")
                    out_sum   = event.get("output_summary") or {}

                    if stage_val == "search":
                        yield _sse(
                            "stage_complete", "search", "Search complete",
                            data={"n_candidates": out_sum.get("n_candidates", "?")},
                        )
                    elif stage_val == "screening":
                        yield _sse(
                            "stage_complete", "screening", "Abstract screening complete",
                            data={
                                "included": out_sum.get("included", "?"),
                                "excluded": out_sum.get("excluded", "?"),
                            },
                        )
                    elif stage_val == "extraction":
                        yield _sse("stage_complete", "extraction", "Data extraction complete")
                    elif stage_val in ("quality", "quality_assessment"):
                        yield _sse("stage_complete", "quality", "Quality assessment complete")
                    elif stage_val == "report":
                        yield _sse("done", message="Review complete")
                        done_seen = True

                elif etype == "screening.abstract_decision":
                    screening_counter += 1
                    if screening_counter % 10 == 0:
                        yield _sse(
                            "progress", "screening",
                            f"Abstract screened: {event.get('decision', '?')}",
                            data={"decision": event.get("decision")},
                        )

                elif etype == "benchmark.evaluation":
                    result_data = {
                        k: v for k, v in event.items() if k not in ("ts", "type")
                    }
                    yield _sse("benchmark", data=result_data)

            else:
                # No new content — poll and check for termination
                await asyncio.sleep(0.5)

                now = time.monotonic()
                if now - last_proc_check >= 5.0:
                    last_proc_check = now
                    rc = process.returncode

                    if rc is not None and rc != 0 and not done_seen:
                        yield _sse("error", message="Pipeline failed — check logs")
                        break

                    current_size: int = await asyncio.to_thread(
                        lambda: log_path.stat().st_size
                    )
                    if current_size != last_file_size:
                        last_file_size   = current_size
                        last_growth_time = now

                    if rc == 0 and not done_seen and (now - last_growth_time >= 10.0):
                        yield _sse("done", message="Review complete")
                        done_seen = True

                if done_seen:
                    break
    finally:
        await asyncio.to_thread(fh.close)


# ---------------------------------------------------------------------------
# Endpoint 3: GET /api/runs/{run_id}/stream
# ---------------------------------------------------------------------------


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    return StreamingResponse(
        _sse_generator(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Endpoint 4: GET /api/runs/{run_id}/papers
# ---------------------------------------------------------------------------


@app.get("/api/runs/{run_id}/papers")
async def get_papers(run_id: str) -> List[Dict[str, Any]]:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    report_path = RUNS[run_id]["run_dir"] / "review_report.json"
    if not report_path.exists():
        return []
    raw = await asyncio.to_thread(
        lambda: json.loads(report_path.read_text(encoding="utf-8"))
    )
    return [
        {
            "pmid":  str(r.get("pmid", "")),
            "title": r.get("title", ""),
            "url":   f"https://pubmed.ncbi.nlm.nih.gov/{r.get('pmid', '')}",
        }
        for r in raw.get("included_records", [])
    ]


# ---------------------------------------------------------------------------
# Endpoint 5: GET /api/runs/{run_id}/report
# ---------------------------------------------------------------------------


@app.get("/api/runs/{run_id}/report")
async def get_report(run_id: str) -> HTMLResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    report_path = RUNS[run_id]["run_dir"] / "review_report.md"
    if not report_path.exists():
        return HTMLResponse("<p>Report not ready</p>")
    content = await asyncio.to_thread(
        lambda: report_path.read_text(encoding="utf-8")
    )
    import markdown as md_lib  # lazy import — not part of core deps
    return HTMLResponse(
        md_lib.markdown(content, extensions=["tables", "fenced_code"])
    )


# ---------------------------------------------------------------------------
# Endpoint 6: GET /api/runs/{run_id}/prisma.svg
# ---------------------------------------------------------------------------


@app.get("/api/runs/{run_id}/prisma.svg")
async def get_prisma(run_id: str) -> Response:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")
    path = RUNS[run_id]["run_dir"] / "prisma_flow.svg"
    if not path.exists():
        return Response("Not ready", status_code=404)
    return FileResponse(str(path), media_type="image/svg+xml")


# ---------------------------------------------------------------------------
# Endpoint 7: GET /
# ---------------------------------------------------------------------------


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("frontend/static/index.html")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("frontend.server:app", host="0.0.0.0", port=8000, reload=False)
