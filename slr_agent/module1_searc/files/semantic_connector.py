"""
semantic_connector.py — Semantic Scholar API Connector
========================================================
API constraints (S2 Academic Graph API with S2 API key):
  - Rate limit : 1 request/second across ALL endpoints
  - Auth header: "x-api-key" for most endpoints, BUT the original working
                 code used "api-key" — kept here as it was confirmed working.
                 S2 docs show both names work depending on account tier.
  - Bulk search: /graph/v1/paper/search/bulk returns up to 1000 results
                 in a SINGLE request. This is the correct endpoint for our
                 use case — it avoids the 1 req/s rate limit entirely since
                 we only need ONE call.

Design decisions:
  1. Single bulk request — no pagination loop, no rate-limit risk.
     The bulk endpoint was specifically designed for this pattern.
  2. Retry on 429 with a 3-second wait (S2 rate limit window is 1 second,
     so 3s is a safe margin before retrying once).
  3. Hard limit clamped to [1, 1000] — the API's documented max for bulk.
  4. "api-key" header (from original working code, not "x-api-key").
  5. openAccessPdf field included — used later by Module 2 for PDF download.
"""

import os
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_API_KEY  = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
_BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_FIELDS   = "title,abstract,year,citationCount,externalIds,openAccessPdf"
_BULK_MAX = 1000   # S2 bulk endpoint documented hard cap


def search(query: str, limit: int = 500) -> list:
    """
    Search Semantic Scholar using a single bulk request.

    Parameters
    ----------
    query : str
        Free-text query string. Keep this as the research question — S2's
        bulk endpoint does its own relevance ranking.
    limit : int
        Max papers to retrieve. Clamped to [1, 1000].
        1000 is the maximum the bulk endpoint will return in one call.

    Returns
    -------
    list of paper dicts:
        title, abstract, doi, year, citation_count, open_access_pdf, source
    """
    # ── Clamp limit ──────────────────────────────────────────────────────────
    original = limit
    limit = max(1, min(limit, _BULK_MAX))
    if limit != original:
        logger.warning(
            "S2 limit clamped %d → %d (bulk endpoint max is %d).",
            original, limit, _BULK_MAX
        )

    logger.info("Semantic Scholar search: '%s'  limit=%d", query[:100], limit)

    params = {
        "query":  query,
        "limit":  limit,
        "fields": _FIELDS,
    }

    # Header that was confirmed working with S2 API key
    headers = {"api-key": _API_KEY} if _API_KEY else {}

    # ── Single request, one retry on 429 ────────────────────────────────────
    # We only need ONE request (bulk endpoint). If we hit the rate limit it
    # means something else in the pipeline made a request in the same second.
    # Wait 3 seconds and try once more.
    for attempt in range(1, 3):
        try:
            resp = requests.get(_BULK_URL, params=params, headers=headers, timeout=30)
        except requests.exceptions.Timeout:
            logger.error("S2 request timed out (attempt %d).", attempt)
            return []
        except requests.exceptions.RequestException as exc:
            logger.error("S2 network error: %s", exc)
            return []

        if resp.status_code == 200:
            break
        elif resp.status_code == 429:
            wait = 3 * attempt
            logger.warning("S2 rate limit (attempt %d). Waiting %ds…", attempt, wait)
            time.sleep(wait)
            continue
        elif resp.status_code == 400:
            logger.error("S2 rejected query (400). Query was: %s", query[:200])
            return []
        elif resp.status_code == 403:
            logger.error(
                "S2 returned 403 Forbidden. Check SEMANTIC_SCHOLAR_API_KEY in .env "
                "(env var name: SEMANTIC_SCHOLAR_API_KEY)."
            )
            return []
        else:
            logger.error("S2 returned HTTP %d.", resp.status_code)
            return []
    else:
        logger.error("S2 failed after retries.")
        return []

    # ── Parse ────────────────────────────────────────────────────────────────
    try:
        data = resp.json()
    except ValueError:
        logger.error("S2 returned non-JSON.")
        return []

    papers = []
    for p in data.get("data", []):
        if not p.get("title"):
            continue
        papers.append({
            "title":           p.get("title"),
            "abstract":        p.get("abstract"),
            "doi":             (p.get("externalIds") or {}).get("DOI"),
            "year":            p.get("year"),
            "citation_count":  p.get("citationCount"),
            "open_access_pdf": ((p.get("openAccessPdf") or {}).get("url")),
            "source":          "semantic_scholar",
        })

    logger.info("S2 returned %d papers.", len(papers))
    return papers