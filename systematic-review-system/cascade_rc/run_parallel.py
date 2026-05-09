"""
Parallel execution of CASCADE-RC pipeline across multiple topics.

Architecture:
  - One subprocess per topic (ProcessPoolExecutor with spawn context)
  - Each subprocess runs the full pipeline for its topic independently
  - Per-topic SQLite cache (P2) eliminates write contention between topics
  - Async LLM calls within each topic (P1) for maximum throughput
  - Calibration runs after all LLM calls complete (fast, CPU-bound)

Usage:
    python -m cascade_rc.run_parallel \\
        --topics CD008874 CD012080 CD012768 CD011768 CD011975 CD011145 \\
        --max-workers 6 \\
        --n-concurrent 20

Expected timing with B=5, ~1800 PMIDs/topic, 6.1s LLM latency:
    Sequential (no parallelisation):  ~23 hours
    Async only (P1):                  ~1.5 hours per topic (sequential topics)
    Async + parallel (P1+P3):         ~25-35 minutes wall-clock
"""
from __future__ import annotations

import argparse
import logging
import multiprocessing
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TOPICS: list[str] = [
    "CD008874", "CD012080", "CD012768",
    "CD011768", "CD011975", "CD011145",
]

# Canonical step ordering (mirrors run_pipeline.STEPS)
ALL_STEPS: list[str] = [
    "ingest", "score_s", "score_u", "merge_u",
    "baselines", "calibrate", "evaluate", "figures",
]


# ---------------------------------------------------------------------------
# Subprocess entry-point
# ---------------------------------------------------------------------------

def run_topic_pipeline(
    topic_id: str,
    steps: list[str],
    n_concurrent: int,
    artefact_dir: str,
    resume: bool,
) -> dict:
    """Run the full pipeline for one topic inside a subprocess.

    All arguments must be picklable (plain strings/lists/ints — no Paths, no
    pydantic models).

    CRC_N_CONCURRENT is injected via the environment *before* any cascade_rc
    imports so that step_score_u's internal CascadeRCConfig() picks up the
    correct value at construction time.
    """
    import os
    import logging as _logging
    import traceback

    # Must happen before any cascade_rc import that touches CascadeRCConfig.
    os.environ["CRC_N_CONCURRENT"] = str(n_concurrent)

    _logging.basicConfig(
        level=_logging.INFO,
        format=f"%(asctime)s %(levelname)s %(name)s [{topic_id}] %(message)s",
        datefmt="%H:%M:%S",
    )

    start = time.monotonic()
    try:
        from cascade_rc.config import CascadeRCConfig
        from cascade_rc.run_pipeline import run_pipeline_for_topic

        config = CascadeRCConfig()
        config.n_concurrent = n_concurrent
        config.artefact_dir = Path(artefact_dir)

        run_pipeline_for_topic(
            topic_id=topic_id,
            config=config,
            steps=steps,
            resume=resume,
        )

        return {
            "topic_id": topic_id,
            "status": "success",
            "elapsed_seconds": time.monotonic() - start,
            "error": None,
        }
    except Exception:
        return {
            "topic_id": topic_id,
            "status": "failed",
            "error": traceback.format_exc(),
            "elapsed_seconds": time.monotonic() - start,
        }


# ---------------------------------------------------------------------------
# Parallel orchestrator
# ---------------------------------------------------------------------------

def run_parallel(
    topic_ids: list[str],
    steps: list[str],
    max_workers: int = 6,
    n_concurrent: int = 20,
    artefact_dir: str | Path = "artefacts/cascade_rc",
    resume: bool = False,
) -> dict[str, dict]:
    """Run pipeline for all topics in parallel using a process pool.

    Args:
        topic_ids:    Topics to process.
        steps:        Pipeline steps to run per topic.
        max_workers:  Max topics running simultaneously (default 6 = all at once).
        n_concurrent: Async LLM concurrency within each topic (default 20).
        artefact_dir: Root artefact directory (certs, results, per-topic cache).
        resume:       Skip steps whose output artefacts already exist.

    Returns:
        Mapping topic_id → {status, elapsed_seconds, error}.

    Rate-limit note:
        Peak concurrent API calls = max_workers × n_concurrent × B (B=5).
        At defaults: 6 × 20 × 5 = 600 in-flight. If the endpoint rate-limits,
        reduce n_concurrent to 10 (→ 300) or max_workers to 3 (→ 300).
    """
    artefact_dir_str = str(artefact_dir)
    peak_calls = max_workers * n_concurrent * 5

    print(
        f"\nParallel pipeline: {len(topic_ids)} topic(s) | "
        f"max_workers={max_workers} | n_concurrent={n_concurrent} | "
        f"peak API calls={peak_calls}"
    )
    print(f"Steps:  {steps}")
    print(f"Topics: {', '.join(topic_ids)}\n")

    wall_start = time.monotonic()
    results: dict[str, dict] = {}

    # Spawn avoids fork-safety issues with asyncio event loops that may already
    # exist in the parent process.
    ctx = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx) as pool:
        futures = {
            pool.submit(
                run_topic_pipeline,
                topic_id=t,
                steps=steps,
                n_concurrent=n_concurrent,
                artefact_dir=artefact_dir_str,
                resume=resume,
            ): t
            for t in topic_ids
        }

        for future in as_completed(futures):
            topic_id = futures[future]
            result = future.result()
            results[topic_id] = result

            elapsed_min = result["elapsed_seconds"] / 60
            sym = "✓" if result["status"] == "success" else "✗"
            print(f"  {sym} {topic_id}: {result['status']} in {elapsed_min:.1f}min")
            if result["status"] == "failed":
                print(result.get("error") or "")

    wall_elapsed = time.monotonic() - wall_start
    succeeded = sum(1 for r in results.values() if r["status"] == "success")

    print(f"\n{'=' * 60}")
    print(f"Complete: {succeeded}/{len(topic_ids)} succeeded | wall={wall_elapsed / 60:.1f}min")
    if succeeded > 0:
        sequential_s = sum(
            r["elapsed_seconds"] for r in results.values() if r["status"] == "success"
        )
        print(
            f"Sequential equivalent: {sequential_s / 3600:.1f}h | "
            f"speedup: {sequential_s / wall_elapsed:.1f}x"
        )
    print(f"{'=' * 60}\n")

    return results


# ---------------------------------------------------------------------------
# Two-phase execution for memory-constrained machines
# ---------------------------------------------------------------------------

def run_two_phase(
    topic_ids: list[str],
    n_concurrent: int = 20,
    max_workers_llm: int = 6,
    artefact_dir: str | Path = "artefacts/cascade_rc",
) -> None:
    """Two-phase execution for memory-constrained machines (~16 GB RAM).

    Phase 1 (parallel, I/O-bound): LLM scoring for all topics simultaneously.
      Each topic's async calls overlap with other topics' calls.

    Phase 2 (sequential, CPU-bound): calibration and evaluation for each topic.
      max_workers=1 avoids any race conditions in shared output directories
      (figures/, results/) and minimises peak memory usage.

    Assumes ingest and score_s have already been run (or uses resume=True to
    skip completed steps automatically).
    """
    print("=" * 60)
    print("Phase 1: Parallel LLM scoring (score_u)")
    print("=" * 60)
    run_parallel(
        topic_ids=topic_ids,
        steps=["score_u"],
        max_workers=max_workers_llm,
        n_concurrent=n_concurrent,
        artefact_dir=artefact_dir,
        resume=True,
    )

    print("=" * 60)
    print("Phase 2: Sequential calibration (no LLM calls)")
    print("=" * 60)
    run_parallel(
        topic_ids=topic_ids,
        steps=["calibrate", "evaluate", "figures"],
        max_workers=1,
        n_concurrent=1,
        artefact_dir=artefact_dir,
        resume=True,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Run CASCADE-RC pipeline in parallel across topics",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--topics", nargs="+", default=DEFAULT_TOPICS, metavar="TOPIC_ID",
        help="Topic IDs to process",
    )
    parser.add_argument(
        "--steps", nargs="+", default=None, metavar="STEP",
        help=f"Pipeline steps to run (default: all). Choices: {ALL_STEPS}",
    )
    parser.add_argument(
        "--max-workers", type=int, default=6,
        help="Max parallel topics (default 6 = all at once)",
    )
    parser.add_argument(
        "--n-concurrent", type=int, default=20,
        help="Async LLM concurrency within each topic",
    )
    parser.add_argument(
        "--artefact-dir", type=Path, default=Path("artefacts/cascade_rc"),
        help="Root artefact directory",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Skip steps whose output artefacts already exist",
    )
    parser.add_argument(
        "--two-phase", action="store_true",
        help="Two-phase mode: parallel LLM scoring then sequential calibration",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would run without executing",
    )
    args = parser.parse_args()

    steps = args.steps or ALL_STEPS

    if args.dry_run:
        peak = args.max_workers * args.n_concurrent * 5
        print("DRY RUN — would execute:")
        print(f"  Topics:         {args.topics}")
        print(f"  Steps:          {steps}")
        print(f"  max_workers:    {args.max_workers}")
        print(f"  n_concurrent:   {args.n_concurrent}")
        print(f"  artefact_dir:   {args.artefact_dir}")
        print(f"  Peak API calls: {args.max_workers} × {args.n_concurrent} × 5 = {peak}")
        return

    if args.two_phase:
        run_two_phase(
            topic_ids=args.topics,
            n_concurrent=args.n_concurrent,
            max_workers_llm=args.max_workers,
            artefact_dir=args.artefact_dir,
        )
        return

    results = run_parallel(
        topic_ids=args.topics,
        steps=steps,
        max_workers=args.max_workers,
        n_concurrent=args.n_concurrent,
        artefact_dir=args.artefact_dir,
        resume=args.resume,
    )

    failed = [t for t, r in results.items() if r["status"] == "failed"]
    if failed:
        logger.error("Failed topics: %s", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
