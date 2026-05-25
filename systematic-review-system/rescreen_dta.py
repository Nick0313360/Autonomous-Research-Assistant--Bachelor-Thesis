"""
rescreen_dta.py
===============
Re-screens the 562 included papers from CD008874_v6 using a strict
Diagnostic Test Accuracy (DTA) prompt to estimate real precision.

Usage:
    python rescreen_dta.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REPORT_JSON   = Path("data/reports/CD008874_v6/review_report.json")
OUTPUT_JSON   = Path("data/reports/CD008874_v6/rescreen_dta.json")
CONCURRENCY   = 20
TRUE_POSITIVES = 123   # known m+ in the included set

_SYSTEM = "You are a systematic review screener for a Cochrane Diagnostic Test Accuracy review."

_PROMPT_TMPL = """\
You are screening papers for a Cochrane Diagnostic Test Accuracy review on airway physical examination tests.

Paper title: {title}
Abstract: {abstract}

Answer these three questions with YES or NO only:
1. Does this paper evaluate a SPECIFIC BEDSIDE PHYSICAL EXAMINATION TEST for predicting difficult airway? \
(e.g. Mallampati score, thyromental distance, sternomental distance, mouth opening, upper lip bite test, Wilson risk score)
2. Is this test compared against a REFERENCE STANDARD for difficult intubation \
(e.g. Cormack-Lehane grade, intubation difficulty scale)?
3. Does the study report DIAGNOSTIC ACCURACY metrics \
(sensitivity, specificity, AUC, likelihood ratio)?

If ALL THREE answers are YES: output INCLUDE
If ANY answer is NO: output EXCLUDE with reason"""


def _parse(text: str) -> tuple[str, str]:
    """Return (decision, reason) from raw LLM text."""
    upper = text.upper()
    if "INCLUDE" in upper and "EXCLUDE" not in upper:
        return "INCLUDE", ""
    m = re.search(r"EXCLUDE[:\s]+(.+)", text, re.IGNORECASE | re.DOTALL)
    reason = m.group(1).strip()[:200] if m else ""
    return "EXCLUDE", reason


async def _screen_one(
    sem: asyncio.Semaphore,
    llm: Any,
    record_id: str,
    pmid: Optional[str],
    title: str,
    abstract: str,
    idx: int,
    total: int,
) -> Dict:
    prompt = _PROMPT_TMPL.format(
        title    = title    or "(no title)",
        abstract = abstract or "(no abstract)",
    )
    async with sem:
        try:
            resp = await llm.complete(
                prompt      = prompt,
                system      = _SYSTEM,
                temperature = 0.0,
                max_tokens  = 256,
                response_format = "text",
            )
            decision, reason = _parse(resp.content)
        except Exception as exc:
            logger.warning("record %s failed: %s", record_id, exc)
            decision, reason = "ERROR", str(exc)

    if idx % 50 == 0:
        logger.info("  progress: %d / %d", idx, total)

    return {
        "record_id": record_id,
        "pmid":      pmid,
        "title":     title,
        "decision":  decision,
        "reason":    reason,
    }


async def main() -> None:
    from infrastructure.llm_client import LLMClient

    # ── load included records ─────────────────────────────────────────────
    report   = json.loads(REPORT_JSON.read_text())
    raw_recs = report["included_records"]
    logger.info("Included papers: %d", len(raw_recs))

    # ── build task list (support both old str format and new dict format) ─
    tasks_data = []
    no_meta = 0
    for rec in raw_recs:
        if isinstance(rec, dict):
            tasks_data.append({
                "record_id": rec.get("record_id", ""),
                "pmid":      str(rec.get("pmid") or ""),
                "title":     str(rec.get("title") or ""),
                "abstract":  str(rec.get("abstract") or ""),
            })
        else:
            # Legacy: plain record_id string — try parquet fallback
            no_meta += 1
            tasks_data.append({
                "record_id": str(rec),
                "pmid":      "",
                "title":     "",
                "abstract":  "",
            })

    if no_meta:
        logger.warning(
            "%d records are plain IDs with no metadata. "
            "Re-run main.py to regenerate review_report.json with enriched records.",
            no_meta,
        )

    # ── run re-screening ─────────────────────────────────────────────────
    llm = LLMClient()
    sem = asyncio.Semaphore(CONCURRENCY)
    total = len(tasks_data)
    logger.info("Starting DTA re-screening (%d papers, concurrency=%d)…", total, CONCURRENCY)

    coros = [
        _screen_one(sem, llm, t["record_id"], t["pmid"], t["title"], t["abstract"], i + 1, total)
        for i, t in enumerate(tasks_data)
    ]
    results = await asyncio.gather(*coros)
    await llm.aclose()

    # ── summarise ────────────────────────────────────────────────────────
    kept     = [r for r in results if r["decision"] == "INCLUDE"]
    excluded = [r for r in results if r["decision"] == "EXCLUDE"]
    errors   = [r for r in results if r["decision"] == "ERROR"]

    n_kept = len(kept)
    precision = TRUE_POSITIVES / n_kept if n_kept > 0 else 0.0

    summary = {
        "original":            total,
        "kept":                n_kept,
        "excluded":            len(excluded),
        "errors":              len(errors),
        "new_precision_est":   round(precision, 4),
        "true_positives":      TRUE_POSITIVES,
        "note": (
            f"Precision = {TRUE_POSITIVES} known m+ / {n_kept} DTA-kept "
            f"= {precision:.1%}"
        ),
    }

    output = {"summary": summary, "results": results}
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print("\n" + "=" * 60)
    print("  DTA RE-SCREENING COMPLETE")
    print("=" * 60)
    print(f"  Original included  : {total}")
    print(f"  Kept (DTA-relevant): {n_kept}")
    print(f"  Excluded by DTA    : {len(excluded)}")
    print(f"  Errors             : {len(errors)}")
    print(f"  New precision est. : {TRUE_POSITIVES}/{n_kept} = {precision:.1%}")
    print(f"  Results saved to   : {OUTPUT_JSON}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
