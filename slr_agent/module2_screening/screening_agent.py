import io
import json
import logging
import os
import time

import requests
from dotenv import load_dotenv
from openai import OpenAI
from pdfminer.high_level import extract_text

load_dotenv()

# ── logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger(__name__)

# ── OpenAI client (same pattern as Module 1) ──────────────────────────────────
_client = OpenAI(
    base_url=os.getenv("API_URL"),
    api_key=os.getenv("OPENAI_API_KEY"),
)
MODEL = os.getenv("SCREENING_MODEL", "gpt-oss:120b")

UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "test@example.com")

# ── default criteria (caller can override) ────────────────────────────────────
DEFAULT_CRITERIA = """
INCLUSION
- Paper presents an empirical evaluation of an AI / ML tool used in at
  least one stage of a systematic review or evidence-synthesis pipeline.
- Written in English.
- Published in or after 2018.

EXCLUSION
- Conference abstracts, posters, editorials, or opinion pieces with no
  empirical data.
- Papers where automation is only discussed theoretically without
  implementation or evaluation.
- Duplicate publication (same dataset, same tool, same results).
"""


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — LLM WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

def _call_llm(prompt: str, max_retries: int = 3) -> dict:
    """
    Send *prompt* to the configured model.
    Returns parsed JSON dict.
    Retries up to *max_retries* times on transient errors.
    """
    for attempt in range(1, max_retries + 1):
        try:
            response = _client.chat.completions.create(
                model=MODEL,
                temperature=0.0,          # deterministic screening
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a systematic review screening expert. "
                            "Always respond with valid JSON only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content.strip()
            return json.loads(raw)

        except json.JSONDecodeError as exc:
            log.warning("Attempt %d — JSON parse error: %s", attempt, exc)
        except Exception as exc:
            log.warning("Attempt %d — LLM error: %s", attempt, exc)
            time.sleep(2 ** attempt)   # exponential back-off

    # final fallback — uncertain so human can review
    return {
        "decision": "uncertain",
        "confidence": 0.0,
        "reason": "LLM call failed after all retries.",
        "supporting_text": "",
    }


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — SUB-STAGE 2A  (title + abstract screening)
# ══════════════════════════════════════════════════════════════════════════════

_TA_PROMPT = """
You are a systematic review screening assistant.

────────────────────────────────────────
INCLUSION / EXCLUSION CRITERIA
────────────────────────────────────────
{criteria}
────────────────────────────────────────

Evaluate the paper below against those criteria.

Title:
{title}

Abstract:
{abstract}

Return ONLY a valid JSON object with exactly these four keys:

{{
  "decision":        "include" | "exclude" | "uncertain",
  "confidence":      <float 0-1>,
  "reason":          "<one concise sentence explaining the decision>",
  "supporting_text": "<verbatim phrase from the abstract that supports the decision>"
}}

Rules:
- Use "uncertain" when the abstract does not provide enough information to
  decide with confidence >= 0.70.
- Prefer "uncertain" over a wrong definitive decision.
- Do NOT add any keys beyond the four listed above.
"""


def screen_title_abstract(paper: dict, criteria: str = DEFAULT_CRITERIA) -> dict:
    """
    Run title/abstract screening for a single *paper*.

    Returns the LLM decision dict enriched with the paper's title and DOI
    for easy logging.
    """
    abstract = paper.get("abstract") or "No abstract available."

    prompt = _TA_PROMPT.format(
        criteria=criteria.strip(),
        title=paper.get("title", ""),
        abstract=abstract,
    )

    result = _call_llm(prompt)

    # always attach identifiers for traceability
    result["_title"] = paper.get("title", "")
    result["_doi"]   = paper.get("doi", "")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — PDF RETRIEVAL  (Unpaywall + Semantic Scholar fallback)
# ══════════════════════════════════════════════════════════════════════════════

def _get_pdf_url_unpaywall(doi: str) -> str | None:
    """Query Unpaywall for the best open-access PDF URL."""
    if not doi:
        return None
    url = f"https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        best = data.get("best_oa_location") or {}
        return best.get("url_for_pdf")
    except Exception as exc:
        log.debug("Unpaywall lookup failed for %s: %s", doi, exc)
        return None


def _get_pdf_url_semantic_scholar(paper: dict) -> str | None:
    """
    Use the openAccessPdf field that Semantic Scholar already returned in
    Module 1 (if present in the paper dict).
    """
    oa = paper.get("openAccessPdf") or {}
    if isinstance(oa, dict):
        return oa.get("url")
    if isinstance(oa, str):
        return oa or None
    return None


def get_pdf_url(paper: dict) -> str | None:
    """
    Try every available source for a free, legal PDF URL.
    Priority: Semantic Scholar field → Unpaywall DOI lookup.
    """
    # 1. Semantic Scholar already gave us the URL
    url = _get_pdf_url_semantic_scholar(paper)
    if url:
        log.debug("PDF via Semantic Scholar for: %s", paper.get("title", ""))
        return url

    # 2. Unpaywall via DOI
    url = _get_pdf_url_unpaywall(paper.get("doi", ""))
    if url:
        log.debug("PDF via Unpaywall for: %s", paper.get("title", ""))
        return url

    return None


def extract_pdf_text(pdf_url: str, max_chars: int = 20_000) -> str | None:
    """
    Download PDF from *pdf_url* and return extracted plain text
    truncated to *max_chars* characters.
    Returns None on any error.
    """
    try:
        r = requests.get(pdf_url, timeout=30)
        r.raise_for_status()
        with io.BytesIO(r.content) as buf:
            text = extract_text(buf)
        return text[:max_chars]
    except Exception as exc:
        log.warning("PDF extraction failed (%s): %s", pdf_url, exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — SUB-STAGE 2B  (full-text screening)
# ══════════════════════════════════════════════════════════════════════════════

_FT_PROMPT = """
You are performing FULL-TEXT eligibility screening for a systematic review.

────────────────────────────────────────
INCLUSION / EXCLUSION CRITERIA
────────────────────────────────────────
{criteria}
────────────────────────────────────────

Paper title:
{title}

Full-text excerpt (first ~20 000 characters):
{text}

Return ONLY a valid JSON object with exactly these four keys:

{{
  "decision":        "include" | "exclude",
  "confidence":      <float 0-1>,
  "reason":          "<one concise sentence explaining the decision>",
  "supporting_text": "<verbatim passage from the text that supports the decision>"
}}

Rules:
- At this stage you must give a definitive include OR exclude — no "uncertain".
- Focus on the Methods section for study design evidence.
- If the excerpt is too short to judge, set decision="exclude" and note it
  in reason so a human can verify.
- Do NOT add any keys beyond the four listed above.
"""


def screen_full_text(paper: dict, text: str, criteria: str = DEFAULT_CRITERIA) -> dict:
    """
    Run full-text eligibility screening for a single *paper*.
    *text* is the extracted PDF content.
    """
    prompt = _FT_PROMPT.format(
        criteria=criteria.strip(),
        title=paper.get("title", ""),
        text=text,
    )
    result = _call_llm(prompt)
    result["_title"] = paper.get("title", "")
    result["_doi"]   = paper.get("doi", "")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run_screening(
    papers: list[dict],
    criteria: str = DEFAULT_CRITERIA,
    uncertain_threshold: float = 0.70,
) -> dict:
    """
    Run the full two-stage screening pipeline.

    Parameters
    ----------
    papers              : list of paper dicts from Module 1
    criteria            : inclusion / exclusion criteria string
    uncertain_threshold : confidence below this → "uncertain" in stage 2A

    Returns
    -------
    dict with keys:
        included_papers          – papers that passed both stages
        excluded_title_abstract  – excluded at 2A with reasons
        excluded_fulltext        – excluded at 2B with reasons
        uncertain                – flagged for human review
        no_pdf                   – passed 2A but no PDF found
        prisma_stats             – PRISMA counts
        decision_log             – full per-paper audit trail
    """

    # ── accumulators ─────────────────────────────────────────────────────────
    ta_pass      = []   # passed 2A → go to 2B
    excluded_ta  = []   # excluded at title/abstract
    uncertain    = []   # uncertain → human review queue
    included     = []   # passed both stages
    excluded_ft  = []   # excluded at full text
    no_pdf       = []   # passed 2A but PDF unavailable
    decision_log = []   # full audit trail

    total = len(papers)
    log.info("Stage 2A — screening %d papers (title/abstract) …", total)

    # ── SUB-STAGE 2A ─────────────────────────────────────────────────────────
    for i, paper in enumerate(papers, 1):
        log.info("  2A [%d/%d] %s", i, total, paper.get("title", "")[:80])

        result = screen_title_abstract(paper, criteria)

        entry = {
            "stage":          "2A",
            "paper":          paper,
            "decision":       result.get("decision"),
            "confidence":     result.get("confidence"),
            "reason":         result.get("reason"),
            "supporting_text":result.get("supporting_text"),
        }
        decision_log.append(entry)

        decision   = result.get("decision", "uncertain")
        confidence = float(result.get("confidence", 0))

        # downgrade low-confidence include/exclude to uncertain
        if decision in ("include", "exclude") and confidence < uncertain_threshold:
            decision = "uncertain"

        if decision == "include":
            ta_pass.append(paper)
        elif decision == "uncertain":
            uncertain.append({"paper": paper, "reason": result.get("reason"), "confidence": confidence})
        else:
            excluded_ta.append({"paper": paper, "reason": result.get("reason")})

    log.info(
        "Stage 2A done — include: %d | exclude: %d | uncertain: %d",
        len(ta_pass), len(excluded_ta), len(uncertain),
    )

    # ── SUB-STAGE 2B ─────────────────────────────────────────────────────────
    log.info("Stage 2B — full-text screening %d papers …", len(ta_pass))

    for i, paper in enumerate(ta_pass, 1):
        log.info("  2B [%d/%d] %s", i, len(ta_pass), paper.get("title", "")[:80])

        # — PDF retrieval —
        pdf_url = get_pdf_url(paper)
        if not pdf_url:
            log.warning("    No PDF found — marking as no_pdf")
            no_pdf.append({"paper": paper, "reason": "full text not available"})
            decision_log.append({
                "stage":     "2B",
                "paper":     paper,
                "decision":  "no_pdf",
                "confidence": None,
                "reason":    "No open-access PDF found via Semantic Scholar or Unpaywall.",
                "supporting_text": "",
            })
            continue

        # — text extraction —
        text = extract_pdf_text(pdf_url)
        if not text or len(text.strip()) < 200:
            log.warning("    PDF extraction returned no usable text")
            no_pdf.append({"paper": paper, "reason": "PDF extraction failed"})
            decision_log.append({
                "stage":     "2B",
                "paper":     paper,
                "decision":  "no_pdf",
                "confidence": None,
                "reason":    "PDF downloaded but text extraction failed.",
                "supporting_text": "",
            })
            continue

        # — LLM full-text screening —
        result = screen_full_text(paper, text, criteria)

        entry = {
            "stage":          "2B",
            "paper":          paper,
            "decision":       result.get("decision"),
            "confidence":     result.get("confidence"),
            "reason":         result.get("reason"),
            "supporting_text":result.get("supporting_text"),
        }
        decision_log.append(entry)

        if result.get("decision") == "include":
            included.append(paper)
        else:
            excluded_ft.append({"paper": paper, "reason": result.get("reason")})

    log.info(
        "Stage 2B done — include: %d | exclude: %d | no_pdf: %d",
        len(included), len(excluded_ft), len(no_pdf),
    )

    # ── PRISMA STATS ─────────────────────────────────────────────────────────
    prisma_stats = {
        "records_screened":            total,
        "excluded_title_abstract":     len(excluded_ta),
        "uncertain_flagged_for_human": len(uncertain),
        "sent_to_fulltext":            len(ta_pass),
        "no_pdf_available":            len(no_pdf),
        "excluded_fulltext":           len(excluded_ft),
        "final_included":              len(included),
    }

    log.info("PRISMA stats: %s", json.dumps(prisma_stats, indent=2))

    return {
        "included_papers":         included,
        "excluded_title_abstract": excluded_ta,
        "excluded_fulltext":       excluded_ft,
        "uncertain":               uncertain,
        "no_pdf":                  no_pdf,
        "prisma_stats":            prisma_stats,
        "decision_log":            decision_log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI  (quick smoke-test)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json, sys

    # accept an optional JSON file of papers from Module 1
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            papers = json.load(f)
    else:
        # tiny mock so you can run without Module 1
        papers = [
            {
                "title": "Automating systematic review screening with GPT-4",
                "abstract": (
                    "We present an AI pipeline that uses GPT-4 to screen "
                    "title/abstracts for systematic reviews, achieving κ=0.87 "
                    "against human reviewers on a benchmark of 500 records."
                ),
                "doi": "10.1234/fake.2024.001",
                "source": "pubmed",
                "openAccessPdf": None,
            },
            {
                "title": "A commentary on the future of evidence synthesis",
                "abstract": (
                    "In this opinion piece we argue that AI will transform "
                    "evidence synthesis over the next decade."
                ),
                "doi": None,
                "source": "pubmed",
                "openAccessPdf": None,
            },
        ]

    results = run_screening(papers)

    print("\n=== PRISMA STATS ===")
    print(json.dumps(results["prisma_stats"], indent=2))

    print("\n=== INCLUDED PAPERS ===")
    for p in results["included_papers"]:
        print(" •", p["title"])

    print("\n=== UNCERTAIN (human review queue) ===")
    for u in results["uncertain"]:
        print(" •", u["paper"]["title"], "—", u["reason"])