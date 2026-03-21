"""
MODULE 4A — Quality Assessment (Fixed)
========================================
Fixes applied from advisory:
  1. assess_one_item(): empty-string guard + markdown fence stripping + regex JSON recovery
  2. time.sleep(1) between checklist items to prevent rate-limit cascade
     (CASP Q10 and ROB2-4 were failing because earlier calls consumed the rate budget)
  3. No timeout= or max_tokens= in create() calls — they crash the LMStudio backend
"""

import json
import logging
import os
import re
import time
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, field_validator

load_dotenv()

log = logging.getLogger(__name__)

_client = OpenAI(
    base_url=os.getenv("API_URL", "https://inference.mlmp.ti.bfh.ch/api/v1"),
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
)
MODEL = os.getenv("QUALITY_MODEL", "gpt-oss:120b")

# ── CASP + ROB checklist (unchanged from original) ────────────────────────────
CASP_QUESTIONS = [
    ("Q1",  "research question objective aim study purpose",
     "Was there a clear research question or objective stated?", 1.5),
    ("Q2",  "study design methodology approach evaluation method",
     "Was the study design appropriate for the research question?", 1.5),
    ("Q3",  "recruitment selection inclusion exclusion criteria dataset",
     "Was the evaluation dataset or study sample clearly described?", 1.0),
    ("Q4",  "data collection measurement tool annotation ground truth",
     "Were data collection methods clearly described and appropriate?", 1.0),
    ("Q5",  "bias confounding limitations threats validity",
     "Was potential bias considered and addressed?", 1.5),
    ("Q6",  "results findings performance metrics evaluation outcomes",
     "Were the results clearly reported with appropriate metrics?", 1.0),
    ("Q7",  "baseline comparison benchmark human reviewer gold standard",
     "Was there an independent comparison baseline or benchmark?", 1.5),
    ("Q8",  "external validation test set held out generalisation",
     "Were the results validated on an external or held-out dataset?", 1.5),
    ("Q9",  "reproducibility replication code data availability open source",
     "Was the study sufficiently reproducible?", 1.0),
    ("Q10", "clinical applicability practical use deployment real world",
     "Were the findings discussed in terms of practical applicability?", 0.5),
]

RISK_OF_BIAS_ITEMS = [
    ("ROB1", "training data test data overlap same dataset evaluation",
     "Was the evaluation dataset independent from the training data?", 1.5),
    ("ROB2", "human reviewer independent annotation inter-rater agreement",
     "Was the human comparison benchmark genuinely independent?", 1.5),
    ("ROB3", "metrics pre-registered prospective evaluation protocol",
     "Were evaluation metrics defined before seeing results?", 1.0),
    ("ROB4", "conflict of interest funding disclosure transparency",
     "Were potential conflicts of interest disclosed?", 0.5),
]

ALL_CHECKLIST_ITEMS = CASP_QUESTIONS + RISK_OF_BIAS_ITEMS
MAX_SCORE = sum(w for _, _, _, w in ALL_CHECKLIST_ITEMS)


# ── Pydantic models (unchanged) ───────────────────────────────────────────────
class ChecklistAnswer(BaseModel):
    question_id:      str
    question_text:    str
    answer:           str
    confidence:       float
    supporting_text:  str
    page:             int

    @field_validator("answer", mode="before")
    @classmethod
    def normalise_answer(cls, v):
        v = str(v).lower().strip()
        return "yes" if v in ("yes", "y", "true", "1") else ("no" if v in ("no", "n", "false", "0") else "unclear")

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp(cls, v):
        return round(max(0.0, min(1.0, float(v))), 3)


class QualityAssessment(BaseModel):
    title:          str
    doi:            Optional[str] = None
    answers:        list[ChecklistAnswer]
    casp_score:     float
    rob_score:      float
    overall_score:  float
    quality_grade:  str


_CASP_PROMPT = """
You are a systematic review methodologist performing critical appraisal.

Paper title: {title}

CASP question: {question}

Relevant excerpts from the paper:
---
{context}
---

Based ONLY on the excerpts above, answer the CASP question.

Return ONLY valid JSON with exactly these four keys:

{{
  "answer": "yes" | "no" | "unclear",
  "confidence": <float 0-1>,
  "supporting_text": "<verbatim phrase from the excerpts>",
  "reasoning": "<one sentence explaining your answer>"
}}
"""


def assess_one_item(
    question_id: str,
    question_text: str,
    retrieval_query: str,
    paper_title: str,
    collection,
    max_retries: int = 2,
) -> dict:
    """
    Assess one CASP/ROB item using RAG.

    Fixes:
    - Empty-string guard before json.loads()
    - Markdown fence stripping
    - Regex recovery for truncated JSON
    - No timeout= or max_tokens= in create()
    """
    fallback = {
        "answer": "unclear", "confidence": 0.0,
        "supporting_text": "", "reasoning": "LLM failed.", "page": 0,
    }

    try:
        from module3_extraction.extractor import retrieve_relevant_chunks
        chunks = retrieve_relevant_chunks(retrieval_query, collection, n_results=4)
    except Exception as exc:
        log.warning("Retrieval failed for %s: %s", question_id, exc)
        return fallback

    if not chunks:
        return fallback

    context = "\n\n".join(
        f"[Excerpt {i+1}, page {c['page']}]\n{c['text']}"
        for i, c in enumerate(chunks)
    )
    prompt = _CASP_PROMPT.format(
        title=paper_title, question=question_text, context=context
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = _client.chat.completions.create(
                model=MODEL,
                temperature=0.0,
                messages=[
                    {"role": "system",
                     "content": "You are a systematic review methodologist. Respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
            )
            raw = response.choices[0].message.content.strip()

            # Fix 1: empty guard
            if not raw:
                log.warning("%s attempt %d — empty response", question_id, attempt)
                time.sleep(5 * attempt)
                continue

            # Fix 2: strip markdown fences
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else raw
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            # Fix 3: try direct parse
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                # Fix 4: regex recovery
                match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
                if match:
                    try:
                        result = json.loads(match.group())
                    except Exception:
                        log.warning("%s attempt %d — JSON recovery failed", question_id, attempt)
                        time.sleep(5 * attempt)
                        continue
                else:
                    log.warning("%s attempt %d — no JSON found in: %s", question_id, attempt, raw[:80])
                    time.sleep(5 * attempt)
                    continue

            # find source page
            page = 0
            if result.get("supporting_text"):
                for chunk in chunks:
                    if result["supporting_text"][:40] in chunk["text"]:
                        page = chunk["page"]
                        break
            result["page"] = page
            return result

        except Exception as exc:
            log.warning("%s attempt %d — error: %s", question_id, attempt, exc)
            time.sleep(5 * attempt)

    return fallback


def compute_scores(answers: list[ChecklistAnswer]) -> tuple[float, float, float, str]:
    casp_ids = {q[0]: q[3] for q in CASP_QUESTIONS}
    rob_ids  = {q[0]: q[3] for q in RISK_OF_BIAS_ITEMS}
    casp_max, rob_max = sum(casp_ids.values()), sum(rob_ids.values())

    casp_e = rob_e = overall_e = 0.0
    for ans in answers:
        w = casp_ids.get(ans.question_id) or rob_ids.get(ans.question_id, 0)
        pts = w if ans.answer == "yes" else (w * 0.5 if ans.answer == "unclear" else 0.0)
        overall_e += pts
        if ans.question_id in casp_ids:
            casp_e += pts
        else:
            rob_e += pts

    cs = round(casp_e / casp_max, 3) if casp_max else 0.0
    rs = round(rob_e  / rob_max,  3) if rob_max  else 0.0
    os_ = round(overall_e / MAX_SCORE, 3) if MAX_SCORE else 0.0
    grade = "high" if os_ >= 0.70 else ("moderate" if os_ >= 0.45 else "low")
    return cs, rs, os_, grade


def assess_paper(paper: dict, collection) -> Optional[QualityAssessment]:
    title = paper.get("title", "unknown")
    log.info("  Assessing: %s", title[:70])
    answers = []

    for question_id, retrieval_query, question_text, _ in ALL_CHECKLIST_ITEMS:
        log.debug("    %s", question_id)

        raw = assess_one_item(
            question_id=question_id,
            question_text=question_text,
            retrieval_query=retrieval_query,
            paper_title=title,
            collection=collection,
        )

        try:
            answers.append(ChecklistAnswer(
                question_id=question_id,
                question_text=question_text,
                answer=raw.get("answer", "unclear"),
                confidence=raw.get("confidence", 0.0),
                supporting_text=raw.get("supporting_text", ""),
                page=raw.get("page", 0),
            ))
        except Exception as exc:
            log.warning("    Pydantic error %s: %s", question_id, exc)
            answers.append(ChecklistAnswer(
                question_id=question_id, question_text=question_text,
                answer="unclear", confidence=0.0, supporting_text="", page=0,
            ))

        # Fix: sleep between items to prevent rate-limit cascade on later questions
        time.sleep(1)

    cs, rs, os_, grade = compute_scores(answers)
    log.info("    Quality: %s (overall=%.2f)", grade, os_)

    return QualityAssessment(
        title=title, doi=paper.get("doi"),
        answers=answers,
        casp_score=cs, rob_score=rs, overall_score=os_, quality_grade=grade,
    )


def run_quality_assessment(included_papers: list[dict], chroma_client) -> dict:
    import hashlib
    assessments, failed = [], []
    log.info("Module 4A — assessing %d papers", len(included_papers))

    for i, paper in enumerate(included_papers, 1):
        title = paper.get("title", "unknown")
        log.info("[%d/%d] %s", i, len(included_papers), title[:70])
        paper_id = hashlib.md5((paper.get("doi") or title).encode()).hexdigest()[:12]

        try:
            collection = chroma_client.get_collection(f"paper-{paper_id}")
        except Exception:
            log.warning("No ChromaDB collection for '%s' — run Module 3 first", title[:60])
            failed.append({"paper": paper, "reason": "No ChromaDB collection"})
            continue

        result = assess_paper(paper, collection)
        if result:
            assessments.append(result.model_dump())
        else:
            failed.append({"paper": paper, "reason": "Assessment failed"})

    grades = [a["quality_grade"] for a in assessments]
    summary = {
        "total_assessed":    len(assessments),
        "high":              grades.count("high"),
        "moderate":          grades.count("moderate"),
        "low":               grades.count("low"),
        "failed":            len(failed),
        "avg_overall_score": round(
            sum(a["overall_score"] for a in assessments) / len(assessments), 3
        ) if assessments else 0.0,
    }
    log.info("Quality complete: %s", summary)
    return {"quality_assessments": assessments, "failed": failed, "summary": summary}