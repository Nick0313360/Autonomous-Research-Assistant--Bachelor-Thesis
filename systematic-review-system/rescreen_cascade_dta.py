"""
rescreen_cascade_dta.py
========================
Re-screens the auto_included papers from CASCADE-RC routing using a strict
Diagnostic Test Accuracy (DTA) prompt to estimate real precision.

Reads:  BASE_OUTPUT/{topic_id}/cascade_routing_decisions.json
Writes: BASE_OUTPUT/{topic_id}/cascade_rescreen_dta.json

Usage:
    python rescreen_cascade_dta.py CD008874
"""
from __future__ import annotations

import argparse
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

BASE_OUTPUT = Path("/Users/nikitagolovanov/Desktop/final_Data")
CONCURRENCY = 20

_SYSTEM = "You are a systematic review screener for a Cochrane Diagnostic Test Accuracy review."

# m+ counts from CLEF-TAR qrels / COPA paper
TRUE_POSITIVES_BY_TOPIC: dict[str, int] = {
    "CD008874": 123,
    "CD012768": 36,
    "CD011145": 162,
}

DTA_PROMPTS: dict[str, str] = {

"CD008874": """\
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
If ANY answer is NO: output EXCLUDE with reason""",

"CD012768": """\
You are screening papers for a Cochrane Diagnostic Test Accuracy review on Xpert MTB/RIF for extrapulmonary TB.

Paper title: {title}
Abstract: {abstract}

Answer YES or NO to each:
1. Does this study evaluate Xpert MTB/RIF or Xpert Ultra as a diagnostic test for tuberculosis?
2. Is it compared against a reference standard (culture, histology, or composite reference standard)?
3. Does it report diagnostic accuracy metrics (sensitivity, specificity, AUC, or likelihood ratio)?

If ALL THREE are YES: output INCLUDE
If ANY is NO: output EXCLUDE with reason""",

"CD011145": """\
You are screening papers for a Cochrane Diagnostic Test Accuracy review on MMSE for dementia detection.

Paper title: {title}
Abstract: {abstract}

Answer YES or NO to each:
1. Does this study evaluate the Mini-Mental State Examination (MMSE) or a direct variant as a screening test \
for cognitive impairment or dementia?
2. Is the MMSE result compared against a clinical reference standard for dementia diagnosis \
(e.g. DSM criteria, clinical diagnosis, neuropsychological battery)?
3. Does it report diagnostic accuracy metrics (sensitivity, specificity, AUC, or likelihood ratio)?

If ALL THREE are YES: output INCLUDE
If ANY is NO: output EXCLUDE with reason""",

}


def _parse(text: str) -> tuple[str, str]:
    """Return (decision, reason) from raw LLM text."""
    upper = text.upper()
    if "INCLUDE" in upper and "EXCLUDE" not in upper:
        return "INCLUDE", ""
    m = re.search(r"EXCLUDE[:\s]+(.+)", text, re.IGNORECASE | re.DOTALL)
    reason = m.group(1).strip()[:200] if m else ""
    return "EXCLUDE", reason


async def _screen_one(
    sem:         asyncio.Semaphore,
    llm:         Any,
    pmid:        Optional[str],
    title:       str,
    abstract:    str,
    s_score:     float,
    prompt_tmpl: str,
    idx:         int,
    total:       int,
) -> Dict:
    prompt = prompt_tmpl.format(
        title    = title    or "(no title)",
        abstract = abstract or "(no abstract)",
    )
    async with sem:
        try:
            resp = await llm.complete(
                prompt          = prompt,
                system          = _SYSTEM,
                temperature     = 0.0,
                max_tokens      = 256,
                response_format = "text",
            )
            decision, reason = _parse(resp.content)
        except Exception as exc:
            logger.warning("pmid=%s failed: %s", pmid, exc)
            decision, reason = "ERROR", str(exc)

    if idx % 50 == 0:
        logger.info("  progress: %d / %d", idx, total)

    return {
        "pmid":     pmid,
        "title":    title,
        "s_score":  s_score,
        "decision": decision,
        "reason":   reason,
    }


async def main(topic_id: str) -> None:
    from infrastructure.llm_client import LLMClient

    if topic_id not in DTA_PROMPTS:
        raise ValueError(
            f"No DTA prompt defined for {topic_id}. "
            f"Available: {list(DTA_PROMPTS)}"
        )
    prompt_tmpl   = DTA_PROMPTS[topic_id]
    true_positives = TRUE_POSITIVES_BY_TOPIC.get(topic_id, 0)

    input_path = BASE_OUTPUT / topic_id / "cascade_routing_decisions.json"
    if not input_path.exists():
        raise FileNotFoundError(
            f"{input_path} not found. "
            f"Run: python run_comparative.py {topic_id} --routing-only"
        )

    data   = json.loads(input_path.read_text())
    papers = data.get("auto_included_papers", [])
    logger.info(
        "Loaded %d auto_included papers from %s", len(papers), input_path
    )

    llm   = LLMClient()
    sem   = asyncio.Semaphore(CONCURRENCY)
    total = len(papers)
    logger.info(
        "Starting DTA re-screening for %s (%d papers, concurrency=%d)…",
        topic_id, total, CONCURRENCY,
    )

    coros = [
        _screen_one(
            sem, llm,
            p.get("pmid"),
            str(p.get("title")    or ""),
            str(p.get("abstract") or ""),
            float(p.get("s_score", 0.0)),
            prompt_tmpl,
            i + 1, total,
        )
        for i, p in enumerate(papers)
    ]
    results = await asyncio.gather(*coros)
    await llm.aclose()

    kept     = [r for r in results if r["decision"] == "INCLUDE"]
    excluded = [r for r in results if r["decision"] == "EXCLUDE"]
    errors   = [r for r in results if r["decision"] == "ERROR"]

    n_kept    = len(kept)
    precision = true_positives / n_kept if n_kept > 0 else 0.0

    # Top 5 exclusion reasons
    reason_counts: Dict[str, int] = {}
    for r in excluded:
        key = (r["reason"] or "no reason")[:80]
        reason_counts[key] = reason_counts.get(key, 0) + 1
    top5 = sorted(reason_counts.items(), key=lambda x: -x[1])[:5]

    summary = {
        "topic_id":          topic_id,
        "auto_included":     total,
        "dta_kept":          n_kept,
        "dta_excluded":      len(excluded),
        "errors":            len(errors),
        "true_positives":    true_positives,
        "new_precision_est": round(precision, 4),
        "note": (
            f"Precision = {true_positives} known m+ / {n_kept} DTA-kept "
            f"= {precision:.1%}"
        ),
        "top_exclusion_reasons": dict(top5),
    }

    output_path = BASE_OUTPUT / topic_id / "cascade_rescreen_dta.json"
    output_path.write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False)
    )

    print("\n" + "=" * 60)
    print(f"  CASCADE DTA RE-SCREENING — {topic_id}")
    print("=" * 60)
    print(f"  Auto-included (CASCADE)  : {total}")
    print(f"  DTA-kept                 : {n_kept}")
    print(f"  DTA-excluded             : {len(excluded)}")
    print(f"  Errors                   : {len(errors)}")
    print(f"  New precision est.       : {true_positives}/{n_kept} = {precision:.1%}")
    print(f"\n  Top 5 exclusion reasons:")
    for reason, cnt in top5:
        print(f"    [{cnt:>4}] {reason}")
    print(f"\n  Results saved to: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="DTA re-screen of CASCADE-RC auto_included papers"
    )
    parser.add_argument(
        "topic_id",
        choices=list(DTA_PROMPTS),
        help="CLEF-TAR topic ID",
    )
    args = parser.parse_args()
    asyncio.run(main(args.topic_id))
