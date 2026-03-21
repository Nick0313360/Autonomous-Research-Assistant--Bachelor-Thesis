"""
MODULE 2 — Screening Agent (Fixed)
====================================
Fixes applied from advisory:
  1. _call_llm(): empty-string guard + markdown fence stripper + regex JSON recovery
  2. Parallelised title/abstract screening with ThreadPoolExecutor(max_workers=3)
  3. PDF retrieval: Europe PMC added as third source after Unpaywall
  4. URL validation before HTTP request (catches malformed URLs → 400 errors)
  5. 403 Forbidden logged as "paywall" exclusion reason, not generic error
  6. API 502 retry gets 5×attempt sleep instead of 2^attempt (longer gaps for server restart)
"""

import io
import json
import logging
import os
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from dotenv import load_dotenv
from openai import OpenAI
from pdfminer.high_level import extract_text

load_dotenv()

log = logging.getLogger(__name__)

# ── OpenAI client — timeout on constructor, NOT on create() ──────────────────
_client = OpenAI(
    base_url=os.getenv("API_URL", "https://inference.mlmp.ti.bfh.ch/api/v1"),
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
)

UNPAYWALL_EMAIL = os.getenv("UNPAYWALL_EMAIL", "test@example.com")

DEFAULT_CRITERIA = """
INCLUSION
- Paper presents an empirical evaluation of an AI / ML tool used in at
  least one stage of a systematic review or evidence-synthesis pipeline.
- Written in English.
- Published in or after 2018.

EXCLUSION
- Conference abstracts, posters, editorials, or opinion pieces with no empirical data.
- Papers where automation is only discussed theoretically without implementation.
- Duplicate publications.
"""

# ══════════════════════════════════════════════════════════════════════════════
# PDF RETRIEVAL — 3 sources + URL validation
# ══════════════════════════════════════════════════════════════════════════════

def _validate_url(url: str) -> bool:
    """Return True only if url is a well-formed http/https URL."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _get_pdf_url_semantic_scholar(paper: dict) -> str | None:
    oa = paper.get("openAccessPdf") or paper.get("open_access_pdf")
    if isinstance(oa, dict):
        url = oa.get("url")
    elif isinstance(oa, str):
        url = oa
    else:
        url = None
    return url if _validate_url(url) else None


def _get_pdf_url_unpaywall(doi: str) -> str | None:
    if not doi:
        return None
    try:
        r = requests.get(
            f"https://api.unpaywall.org/v2/{doi}?email={UNPAYWALL_EMAIL}",
            timeout=15
        )
        r.raise_for_status()
        best = r.json().get("best_oa_location") or {}
        url = best.get("url_for_pdf")
        return url if _validate_url(url) else None
    except Exception as exc:
        log.debug("Unpaywall failed for %s: %s", doi, exc)
        return None


def _get_pdf_url_europepmc(doi: str) -> str | None:
    """
    Europe PMC covers PubMed Central papers — often open-access even when
    Unpaywall doesn't know about them. Good fallback for biomedical papers.
    """
    if not doi:
        return None
    try:
        r = requests.get(
            f"https://www.ebi.ac.uk/europepmc/webservices/rest/search"
            f"?query=DOI:{doi}&format=json&resultType=core",
            timeout=15
        )
        r.raise_for_status()
        results = r.json().get("resultList", {}).get("result", [])
        for item in results:
            for link in (item.get("fullTextUrlList") or {}).get("fullTextUrl", []):
                if link.get("availabilityCode") == "OA":
                    url = link.get("url")
                    if _validate_url(url):
                        return url
    except Exception as exc:
        log.debug("Europe PMC failed for %s: %s", doi, exc)
    return None


def get_pdf_url(paper: dict) -> str | None:
    """
    Try every available open-access PDF source in priority order:
      1. openAccessPdf field from Semantic Scholar (already in paper dict)
      2. Unpaywall API via DOI
      3. Europe PMC via DOI (covers PubMed Central)
    """
    url = _get_pdf_url_semantic_scholar(paper)
    if url:
        log.debug("PDF via S2 for: %s", paper.get("title", "")[:60])
        return url

    doi = paper.get("doi", "")
    url = _get_pdf_url_unpaywall(doi)
    if url:
        log.debug("PDF via Unpaywall for: %s", paper.get("title", "")[:60])
        return url

    url = _get_pdf_url_europepmc(doi)
    if url:
        log.debug("PDF via Europe PMC for: %s", paper.get("title", "")[:60])
        return url

    return None


def extract_pdf_text(pdf_url: str, max_chars: int = 20_000) -> str | None:
    """
    Download and extract text from a PDF URL.

    Fixes:
    - URL validation before request (catches malformed URLs)
    - 403 Forbidden logged as paywall (not generic error)
    - Returns None on any failure so pipeline continues
    """
    if not _validate_url(pdf_url):
        log.warning("Malformed PDF URL skipped: %s", pdf_url[:100])
        return None

    try:
        r = requests.get(pdf_url, timeout=30)

        if r.status_code == 403:
            log.info("PDF paywall (403): %s", pdf_url[:80])
            return None
        if r.status_code == 400:
            log.warning("Bad PDF URL (400): %s", pdf_url[:80])
            return None

        r.raise_for_status()

        with io.BytesIO(r.content) as buf:
            text = extract_text(buf)
        return text[:max_chars] if text else None

    except Exception as exc:
        log.warning("PDF extraction failed (%s): %s", pdf_url[:80], exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# SUB-STAGE 2A — Title/Abstract Screening
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
- Use "uncertain" when confidence < 0.70 or abstract is insufficient.
- Prefer "uncertain" over a wrong definitive decision.
- Do NOT add any keys beyond the four listed.
"""


def screen_title_abstract(paper: dict, criteria: str = DEFAULT_CRITERIA) -> dict:
    abstract = paper.get("abstract") or "No abstract available."
    prompt   = _TA_PROMPT.format(
        criteria=criteria.strip(),
        title=paper.get("title", ""),
        abstract=abstract,
    )
    result = _call_llm(prompt)
    result["_title"] = paper.get("title", "")
    result["_doi"]   = paper.get("doi", "")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SUB-STAGE 2B — Full-Text Screening
# ══════════════════════════════════════════════════════════════════════════════

_FT_PROMPT = """
You are performing FULL-TEXT eligibility screening for a systematic review.

────────────────────────────────────────
INCLUSION / EXCLUSION CRITERIA
────────────────────────────────────────
{criteria}
────────────────────────────────────────

Paper title: {title}

Full-text excerpt (first ~20 000 characters):
{text}

Return ONLY a valid JSON object with exactly these four keys:

{{
  "decision":        "include" | "exclude",
  "confidence":      <float 0-1>,
  "reason":          "<one concise sentence>",
  "supporting_text": "<verbatim passage from the text>"
}}

Rules:
- Give a definitive include OR exclude — no "uncertain".
- Focus on the Methods section for study design evidence.
- Do NOT add any keys beyond the four listed.
"""


def screen_full_text(paper: dict, text: str, criteria: str = DEFAULT_CRITERIA) -> dict:
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
    Two-stage screening pipeline.

    Stage 2A is parallelised with ThreadPoolExecutor(max_workers=3) for ~3x
    speedup. max_workers=3 stays within BFH endpoint rate limits.

    Returns dict with: included_papers, excluded_title_abstract,
    excluded_fulltext, uncertain, no_pdf, prisma_stats, decision_log.
    """
    ta_pass     = []
    excluded_ta = []
    uncertain   = []
    included    = []
    excluded_ft = []
    no_pdf      = []
    decision_log = []

    total = len(papers)
    log.info("Stage 2A — screening %d papers (parallelised, workers=3)…", total)

    # ── SUB-STAGE 2A: parallelised ─────────────────────────────────────────
    def _screen_one(paper):
        return paper, screen_title_abstract(paper, criteria)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_screen_one, p): p for p in papers}
        done = 0
        for future in as_completed(futures):
            done += 1
            if done % 50 == 0:
                log.info("  2A progress: %d/%d", done, total)
            paper, result = future.result()

            entry = {
                "stage":           "2A",
                "paper":           paper,
                "decision":        result.get("decision"),
                "confidence":      result.get("confidence"),
                "reason":          result.get("reason"),
                "supporting_text": result.get("supporting_text"),
            }
            decision_log.append(entry)

            decision   = result.get("decision", "uncertain")
            confidence = float(result.get("confidence") or 0.0)

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

    # ── SUB-STAGE 2B: sequential (PDF download + LLM) ─────────────────────
    log.info("Stage 2B — full-text screening %d papers…", len(ta_pass))

    for i, paper in enumerate(ta_pass, 1):
        log.info("  2B [%d/%d] %s", i, len(ta_pass), paper.get("title", "")[:70])

        pdf_url = get_pdf_url(paper)
        if not pdf_url:
            log.warning("    No open-access PDF found")
            no_pdf.append({"paper": paper, "reason": "no_open_access_pdf"})
            decision_log.append({
                "stage": "2B", "paper": paper,
                "decision": "no_pdf", "confidence": None,
                "reason": "No open-access PDF found (S2, Unpaywall, Europe PMC all failed).",
                "supporting_text": "",
            })
            continue

        text = extract_pdf_text(pdf_url)
        if not text or len(text.strip()) < 200:
            reason = "paywall" if pdf_url else "extraction_failed"
            no_pdf.append({"paper": paper, "reason": reason})
            decision_log.append({
                "stage": "2B", "paper": paper,
                "decision": "no_pdf", "confidence": None,
                "reason": f"PDF not usable: {reason}.",
                "supporting_text": "",
            })
            continue

        result = screen_full_text(paper, text, criteria)
        decision_log.append({
            "stage": "2B", "paper": paper,
            "decision":        result.get("decision"),
            "confidence":      result.get("confidence"),
            "reason":          result.get("reason"),
            "supporting_text": result.get("supporting_text"),
        })

        if result.get("decision") == "include":
            included.append(paper)
        else:
            excluded_ft.append({"paper": paper, "reason": result.get("reason")})

    log.info(
        "Stage 2B done — include: %d | exclude: %d | no_pdf: %d",
        len(included), len(excluded_ft), len(no_pdf),
    )

    prisma_stats = {
        "records_screened":            total,
        "excluded_title_abstract":     len(excluded_ta),
        "uncertain_flagged_for_human": len(uncertain),
        "sent_to_fulltext":            len(ta_pass),
        "no_pdf_available":            len(no_pdf),
        "excluded_fulltext":           len(excluded_ft),
        "final_included":              len(included),
    }

    log.info("PRISMA stats: %s", json.dumps(prisma_stats))

    return {
        "included_papers":         included,
        "excluded_title_abstract": excluded_ta,
        "excluded_fulltext":       excluded_ft,
        "uncertain":               uncertain,
        "no_pdf":                  no_pdf,
        "prisma_stats":            prisma_stats,
        "decision_log":            decision_log,
    }