"""
MODULE 4 — Part A: Quality Assessment
=======================================
Automated CASP (Critical Appraisal Skills Programme) quality assessment
for each included paper, plus risk-of-bias evaluation.

How it works:
  - Uses the same RAG infrastructure as Module 3 (ChromaDB collections
    are already built — we just reuse them here)
  - Each CASP question becomes a retrieval query + LLM prompt
  - LLM answers: yes / no / unclear + confidence + supporting passage
  - 10 CASP questions + 4 risk-of-bias items = 14 checks per paper
  - Final quality score = weighted sum of yes answers (0-1)

Why this is the unique contribution of your thesis:
  Van Dinter et al. documented that automated quality assessment had
  poor inter-rater reliability. Nobody implemented CASP-style automated
  appraisal. This module does it fully, reproducibly, and logged.
"""

import json
import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, field_validator

load_dotenv()

log = logging.getLogger(__name__)

# ── LLM client (same BFH proxy as all other modules) ─────────────────────────
_client = OpenAI(
    base_url=os.getenv("API_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
)
MODEL = os.getenv("QUALITY_MODEL", "gpt-oss:120b")


# ══════════════════════════════════════════════════════════════════════════════
# CASP CHECKLIST
# Each item: (question_id, retrieval_query, question_text, weight)
#
# weight: how much this question contributes to the final score
# Critical questions (e.g. clear research question) weight more than
# minor ones (e.g. ethical considerations)
# ══════════════════════════════════════════════════════════════════════════════

CASP_QUESTIONS = [
    # ── Section A: Are the results valid? ────────────────────────────────────
    (
        "Q1",
        "research question objective aim study purpose",
        "Was there a clear research question or objective stated?",
        1.5,   # critical — papers without a clear question are low quality
    ),
    (
        "Q2",
        "study design methodology approach evaluation method",
        "Was the study design appropriate for the research question?",
        1.5,
    ),
    (
        "Q3",
        "recruitment selection inclusion exclusion criteria dataset",
        "Was the evaluation dataset or study sample clearly described?",
        1.0,
    ),
    (
        "Q4",
        "data collection measurement tool annotation ground truth",
        "Were data collection methods clearly described and appropriate?",
        1.0,
    ),
    (
        "Q5",
        "bias confounding limitations threats validity",
        "Was potential bias considered and addressed?",
        1.5,
    ),
    # ── Section B: What are the results? ─────────────────────────────────────
    (
        "Q6",
        "results findings performance metrics evaluation outcomes",
        "Were the results clearly reported with appropriate metrics?",
        1.0,
    ),
    (
        "Q7",
        "baseline comparison benchmark human reviewer gold standard",
        "Was there an independent comparison baseline or benchmark?",
        1.5,   # critical for AI evaluation papers
    ),
    (
        "Q8",
        "external validation test set held out generalisation",
        "Were the results validated on an external or held-out dataset?",
        1.5,
    ),
    # ── Section C: Will the results help? ────────────────────────────────────
    (
        "Q9",
        "reproducibility replication code data availability open source",
        "Was the study sufficiently reproducible (code/data available)?",
        1.0,
    ),
    (
        "Q10",
        "clinical applicability practical use deployment real world",
        "Were the findings discussed in terms of practical applicability?",
        0.5,
    ),
]

# ── Risk of Bias items (specific to AI evaluation papers) ────────────────────
RISK_OF_BIAS_ITEMS = [
    (
        "ROB1",
        "training data test data overlap same dataset evaluation",
        "Was the evaluation dataset independent from the training data "
        "(no overfitting risk)?",
        1.5,
    ),
    (
        "ROB2",
        "human reviewer independent annotation inter-rater agreement",
        "Was the human comparison benchmark genuinely independent?",
        1.5,
    ),
    (
        "ROB3",
        "metrics pre-registered prospective evaluation protocol",
        "Were evaluation metrics defined before seeing results "
        "(not chosen post-hoc)?",
        1.0,
    ),
    (
        "ROB4",
        "conflict of interest funding disclosure transparency",
        "Were potential conflicts of interest disclosed?",
        0.5,
    ),
]

ALL_CHECKLIST_ITEMS = CASP_QUESTIONS + RISK_OF_BIAS_ITEMS

# max possible score (sum of all weights for a "yes" on every item)
MAX_SCORE = sum(w for _, _, _, w in ALL_CHECKLIST_ITEMS)


# ══════════════════════════════════════════════════════════════════════════════
# PYDANTIC SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

class ChecklistAnswer(BaseModel):
    """Answer to one CASP or risk-of-bias question."""
    question_id:      str
    question_text:    str
    answer:           str            # "yes" | "no" | "unclear"
    confidence:       float          # 0-1
    supporting_text:  str            # verbatim passage from paper
    page:             int            # page number where evidence was found

    @field_validator("answer", mode="before")
    @classmethod
    def normalise_answer(cls, v):
        v = str(v).lower().strip()
        if v in ("yes", "y", "true", "1"):
            return "yes"
        if v in ("no", "n", "false", "0"):
            return "no"
        return "unclear"

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v):
        v = float(v)
        return round(max(0.0, min(1.0, v)), 3)


class QualityAssessment(BaseModel):
    """Full quality assessment for one paper."""
    title:             str
    doi:               Optional[str]  = None

    # individual answers for all 14 checklist items
    answers:           list[ChecklistAnswer]

    # derived scores
    casp_score:        float   # 0-1, based on Q1-Q10 only
    rob_score:         float   # 0-1, based on ROB1-ROB4 only
    overall_score:     float   # 0-1, weighted combination of all items

    # qualitative grade
    quality_grade:     str     # "high" | "moderate" | "low"

    @field_validator("quality_grade", mode="before")
    @classmethod
    def derive_grade(cls, v):
        return v  # set externally based on overall_score


# ══════════════════════════════════════════════════════════════════════════════
# ASSESSMENT PROMPT
# ══════════════════════════════════════════════════════════════════════════════

_CASP_PROMPT = """
You are a systematic review methodologist performing critical appraisal.

Paper title: {title}

CASP question: {question}

Relevant excerpts from the paper:
---
{context}
---

Based ONLY on the excerpts above, answer the CASP question.

CRITICAL RULES:
- Answer based only on what is explicitly stated in the excerpts.
- If the excerpts do not contain enough information, answer "unclear".
- Do NOT use your general knowledge about the paper or topic.

Return ONLY valid JSON with exactly these four keys:

{{
  "answer": "yes" | "no" | "unclear",
  "confidence": <float 0-1>,
  "supporting_text": "<verbatim phrase from the excerpts supporting your answer>",
  "reasoning": "<one sentence explaining your answer>"
}}
"""


# ══════════════════════════════════════════════════════════════════════════════
# CORE ASSESSMENT FUNCTION
# ══════════════════════════════════════════════════════════════════════════════

def assess_one_item(
    question_id: str,
    question_text: str,
    retrieval_query: str,
    paper_title: str,
    collection,           # ChromaDB collection (already built by Module 3)
    max_retries: int = 2,
) -> dict:
    """
    Assess ONE checklist item for ONE paper.

    Process:
      1. Use the retrieval_query to find relevant chunks in ChromaDB
         (same collection built during Module 3 extraction)
      2. Pass those chunks as context to the LLM
      3. LLM answers yes/no/unclear with confidence + supporting text

    Returns raw dict — caller wraps in ChecklistAnswer Pydantic model.
    """
    # ── retrieve relevant chunks (reusing Module 3 ChromaDB collections) ─────
    try:
        # import here to avoid circular dependency
        from extractor import retrieve_relevant_chunks, embed_text

        chunks = retrieve_relevant_chunks(
            query=retrieval_query,
            collection=collection,
            n_results=4,
        )
    except Exception as exc:
        log.warning("Retrieval failed for %s: %s", question_id, exc)
        chunks = []

    if not chunks:
        # no chunks found — return unclear
        return {
            "answer":          "unclear",
            "confidence":      0.0,
            "supporting_text": "",
            "reasoning":       "No relevant text found in paper.",
            "page":            0,
        }

    # ── build context from retrieved chunks ───────────────────────────────────
    context = "\n\n".join(
        f"[Excerpt {i+1}, page {c['page']}]\n{c['text']}"
        for i, c in enumerate(chunks)
    )

    prompt = _CASP_PROMPT.format(
        title=paper_title,
        question=question_text,
        context=context,
    )

    # ── call LLM with retries ─────────────────────────────────────────────────
    for attempt in range(1, max_retries + 1):
        try:
            response = _client.chat.completions.create(
                model=MODEL,
                temperature=0.0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a systematic review methodologist. "
                            "Respond with valid JSON only. "
                            "Never infer — only use the provided excerpts."
                        )
                    },
                    {"role": "user", "content": prompt}
                ]
            )

            raw = response.choices[0].message.content.strip()

            # strip markdown fences if model added them
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            result = json.loads(raw)

            # find source page
            page = 0
            if result.get("supporting_text"):
                for chunk in chunks:
                    if result["supporting_text"][:40] in chunk["text"]:
                        page = chunk["page"]
                        break

            result["page"] = page
            return result

        except json.JSONDecodeError as exc:
            log.warning("%s attempt %d — JSON error: %s", question_id, attempt, exc)
        except Exception as exc:
            log.warning("%s attempt %d — LLM error: %s", question_id, attempt, exc)
            time.sleep(2 ** attempt)

    # all retries failed
    return {
        "answer": "unclear",
        "confidence": 0.0,
        "supporting_text": "",
        "reasoning": "LLM failed after all retries.",
        "page": 0,
    }


def compute_scores(answers: list[ChecklistAnswer]) -> tuple[float, float, float, str]:
    """
    Compute CASP score, ROB score, overall score, and quality grade.

    Scoring logic:
      yes     = full weight
      unclear = half weight (benefit of the doubt)
      no      = zero weight

    Returns (casp_score, rob_score, overall_score, grade)
    All scores are 0-1 floats.
    """
    casp_items = {q[0]: q[3] for q in CASP_QUESTIONS}       # id → weight
    rob_items  = {q[0]: q[3] for q in RISK_OF_BIAS_ITEMS}   # id → weight

    casp_max     = sum(casp_items.values())
    rob_max      = sum(rob_items.values())
    overall_max  = MAX_SCORE

    casp_earned    = 0.0
    rob_earned     = 0.0
    overall_earned = 0.0

    for ans in answers:
        qid    = ans.question_id
        weight = casp_items.get(qid) or rob_items.get(qid, 0)

        if ans.answer == "yes":
            points = weight
        elif ans.answer == "unclear":
            points = weight * 0.5
        else:
            points = 0.0

        overall_earned += points

        if qid in casp_items:
            casp_earned += points
        elif qid in rob_items:
            rob_earned += points

    casp_score    = round(casp_earned / casp_max, 3)    if casp_max    else 0.0
    rob_score     = round(rob_earned  / rob_max,  3)    if rob_max     else 0.0
    overall_score = round(overall_earned / overall_max, 3) if overall_max else 0.0

    # quality grade thresholds (can be adjusted)
    if overall_score >= 0.70:
        grade = "high"
    elif overall_score >= 0.45:
        grade = "moderate"
    else:
        grade = "low"

    return casp_score, rob_score, overall_score, grade


def assess_paper(paper: dict, collection) -> Optional[QualityAssessment]:
    """
    Run the full CASP + risk-of-bias assessment for ONE paper.

    Reuses the ChromaDB collection built during Module 3 extraction —
    no new PDF download or chunking needed.

    Returns QualityAssessment Pydantic object or None on failure.
    """
    title = paper.get("title", "unknown")
    log.info("  Assessing quality: %s", title[:70])

    answers = []

    for question_id, retrieval_query, question_text, weight in ALL_CHECKLIST_ITEMS:
        log.debug("    %s: %s", question_id, question_text[:60])

        raw = assess_one_item(
            question_id=question_id,
            question_text=question_text,
            retrieval_query=retrieval_query,
            paper_title=title,
            collection=collection,
        )

        try:
            answer = ChecklistAnswer(
                question_id=question_id,
                question_text=question_text,
                answer=raw.get("answer", "unclear"),
                confidence=raw.get("confidence", 0.0),
                supporting_text=raw.get("supporting_text", ""),
                page=raw.get("page", 0),
            )
            answers.append(answer)
            log.debug("    → %s (conf: %.2f)", answer.answer, answer.confidence)

        except Exception as exc:
            log.warning("    Pydantic error for %s: %s", question_id, exc)
            # add a fallback unclear answer so the paper isn't skipped entirely
            answers.append(ChecklistAnswer(
                question_id=question_id,
                question_text=question_text,
                answer="unclear",
                confidence=0.0,
                supporting_text="",
                page=0,
            ))

    # compute scores
    casp_score, rob_score, overall_score, grade = compute_scores(answers)

    log.info(
        "    Quality: %s (overall=%.2f, casp=%.2f, rob=%.2f)",
        grade, overall_score, casp_score, rob_score
    )

    return QualityAssessment(
        title=title,
        doi=paper.get("doi"),
        answers=answers,
        casp_score=casp_score,
        rob_score=rob_score,
        overall_score=overall_score,
        quality_grade=grade,
    )


def run_quality_assessment(
    included_papers: list[dict],
    chroma_client,
) -> dict:
    """
    Run CASP quality assessment on all included papers.

    Reuses ChromaDB collections built during Module 3 — no re-indexing.

    Input:
      included_papers : list of paper dicts (same as Module 3 input)
      chroma_client   : the ChromaDB client instance from extractor.py

    Output dict:
      quality_assessments : list of QualityAssessment dicts
      failed              : papers where assessment failed
      summary             : grade distribution counts
    """
    import hashlib

    assessments = []
    failed      = []

    log.info("Module 4A — assessing quality of %d papers", len(included_papers))

    for i, paper in enumerate(included_papers, 1):
        title = paper.get("title", "unknown")
        log.info("[%d/%d] %s", i, len(included_papers), title[:70])

        # get the ChromaDB collection for this paper
        # (same ID logic as extractor.py — must match exactly)
        paper_id = hashlib.md5(
            (paper.get("doi") or title).encode()
        ).hexdigest()[:12]
        collection_name = f"paper-{paper_id}"

        try:
            collection = chroma_client.get_collection(collection_name)
        except Exception:
            log.warning(
                "  No ChromaDB collection found for '%s' — "
                "run Module 3 first to index this paper", title[:60]
            )
            failed.append({"paper": paper, "reason": "No ChromaDB collection — run Module 3 first"})
            continue

        result = assess_paper(paper, collection)

        if result:
            assessments.append(result.model_dump())
        else:
            failed.append({"paper": paper, "reason": "Assessment failed"})

    # grade distribution summary
    grades = [a["quality_grade"] for a in assessments]
    summary = {
        "total_assessed": len(assessments),
        "high":           grades.count("high"),
        "moderate":       grades.count("moderate"),
        "low":            grades.count("low"),
        "failed":         len(failed),
        "avg_overall_score": round(
            sum(a["overall_score"] for a in assessments) / len(assessments), 3
        ) if assessments else 0.0,
    }

    log.info("Quality assessment complete: %s", summary)

    return {
        "quality_assessments": assessments,
        "failed":              failed,
        "summary":             summary,
    }