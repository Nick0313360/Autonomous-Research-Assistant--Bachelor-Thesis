"""
tier1_search/semantic_scholar_connector.py
===========================================
Semantic Scholar Academic Graph connector via the bulk search endpoint.

Credentials are read from environment / config.settings:
    SEMANTIC_SCHOLAR_API_KEY — optional; raises rate limit from 100 → 1000 req/min

Public interface expected by DatabaseConnector:
    SemanticScholarConnector()            ← no-arg constructor
    await connector.search(query)         ← async, returns List[CandidateRecord]
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Bulk endpoint requires an API key; standard endpoint is open (100 req/5 min)
_BULK_URL     = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
_STANDARD_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS       = "title,abstract,year,externalIds,openAccessPdf,authors"
_BULK_MAX     = 1000    # hard cap on bulk endpoint
_STANDARD_MAX = 100     # safe page size for unauthenticated requests
_RETRY_WAIT   = 3       # seconds before re-trying on 429


def _build_s2_query(query) -> str:
    """
    Convert a SearchQuery into a Semantic Scholar query string.

    If query.s2_query_override is set (populated by LLMQueryBuilder), it is
    returned directly — this is the preferred path because the LLM selects only
    3–5 individual keywords with no quotes or Boolean operators.

    Rule-based fallback:
    S2 bulk endpoint treats every space-separated word as a required AND term.
    We therefore use only the 3–5 most specific individual keywords from the
    intervention field, falling back to domain_keywords.
    """
    if query.s2_query_override:
        return query.s2_query_override

    from tier1_search.query_builder import _extract_phrases

    keywords = list(dict.fromkeys(kw.strip() for kw in query.domain_keywords if kw.strip()))
    if not keywords:
        return query.research_question.strip()

    _MAX = 5

    from tier1_search.query_builder import _STOPWORDS

    def _content_words(text: str) -> list[str]:
        return [
            w for w in text.split()
            if w.lower() not in _STOPWORDS and len(w) >= 3
        ]

    if query.intervention:
        int_phrases = _extract_phrases(query.intervention)
        if int_phrases:
            words: list[str] = []
            for phrase in int_phrases:
                words.extend(_content_words(phrase))
                if len(words) >= _MAX:
                    break
            words = list(dict.fromkeys(words[:_MAX]))
            if words:
                return " ".join(words)

    # Fallback: content words from top domain_keywords
    words = []
    for kw in sorted(keywords, key=lambda k: len(k.split()), reverse=True):
        words.extend(_content_words(kw))
        if len(words) >= _MAX:
            break
    words = list(dict.fromkeys(words[:_MAX]))
    return " ".join(words) if words else query.research_question.strip()


class SemanticScholarConnector:
    """
    Semantic Scholar search via the bulk endpoint, wrapped in an async interface.
    Blocking HTTP calls run in a thread-pool executor.
    """

    def __init__(self) -> None:
        self._api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
        if self._api_key:
            logger.info("SemanticScholarConnector: using API key")
        else:
            logger.warning(
                "SemanticScholarConnector: SEMANTIC_SCHOLAR_API_KEY not set. "
                "Semantic Scholar now requires a free API key for all endpoints. "
                "Register at https://www.semanticscholar.org/product/api — "
                "results from this source will be skipped."
            )

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def search(self, query) -> list:
        """
        Execute Semantic Scholar bulk search for *query*.
        Blocking requests.get runs in the default thread-pool executor.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_sync, query)

    # ------------------------------------------------------------------
    # Synchronous implementation (runs in executor)
    # ------------------------------------------------------------------

    def _search_sync(self, query) -> list:
        if not self._api_key:
            return []   # warning already emitted at init time

        s2_query = _build_s2_query(query)
        return self._search_bulk(s2_query, min(query.max_papers_per_db, _BULK_MAX))

    def _search_bulk(self, s2_query: str, max_results: int) -> list:
        logger.info(
            "SemanticScholarConnector (bulk): query='%s'  limit=%d",
            s2_query[:120], max_results,
        )
        params  = {"query": s2_query, "limit": max_results, "fields": _FIELDS}
        headers = {"api-key": self._api_key}

        response = self._request_with_retry(_BULK_URL, params, headers)
        if response is None:
            return []

        try:
            data = response.json()
        except ValueError:
            logger.error("SemanticScholarConnector: non-JSON response")
            return []

        logger.info(
            "SemanticScholarConnector: total=%s  items=%d",
            data.get("total", "?"), len(data.get("data", [])),
        )
        records = []
        for item in data.get("data", []):
            c = self._parse_record(item)
            if c:
                records.append(c)
        logger.info("SemanticScholarConnector: returning %d records", len(records))
        return records

    def _search_standard(self, s2_query: str, max_results: int) -> list:
        """Paginated search on the open endpoint (no API key required)."""
        logger.info(
            "SemanticScholarConnector (standard): query='%s'  limit=%d",
            s2_query[:120], max_results,
        )
        records: list = []
        offset = 0

        while len(records) < max_results:
            page_limit = min(_STANDARD_MAX, max_results - len(records))
            params = {
                "query":  s2_query,
                "limit":  page_limit,
                "offset": offset,
                "fields": _FIELDS,
            }
            response = self._request_with_retry(_STANDARD_URL, params, {})
            if response is None:
                break

            try:
                data = response.json()
            except ValueError:
                logger.error("SemanticScholarConnector: non-JSON response")
                break

            page_data = data.get("data", [])
            if not page_data:
                break

            for item in page_data:
                c = self._parse_record(item)
                if c:
                    records.append(c)

            # S2 standard endpoint returns next token when more pages exist
            if not data.get("next") or len(records) >= max_results:
                break

            offset += page_limit
            time.sleep(0.5)   # stay well under unauthenticated rate limit

        logger.info("SemanticScholarConnector: returning %d records", len(records))
        return records

    def _request_with_retry(self, url: str, params: dict, headers: dict) -> Optional[requests.Response]:
        for attempt in range(1, 4):
            try:
                response = requests.get(
                    url,
                    params  = params,
                    headers = headers,
                    timeout = 30,
                )
            except requests.exceptions.Timeout:
                logger.error("SemanticScholarConnector: request timed out (attempt %d)", attempt)
                return None
            except requests.exceptions.RequestException as exc:
                logger.error("SemanticScholarConnector: network error: %s", exc)
                return None

            if response.status_code == 200:
                return response

            if response.status_code == 429:
                wait = _RETRY_WAIT * attempt
                logger.warning(
                    "SemanticScholarConnector: rate-limited (attempt %d) — waiting %ds",
                    attempt, wait,
                )
                time.sleep(wait)
                continue

            if response.status_code == 400:
                logger.error(
                    "SemanticScholarConnector: query rejected (400): '%s'",
                    params.get("query", "")[:200],
                )
                return None

            if response.status_code == 403:
                logger.error(
                    "SemanticScholarConnector: 403 Forbidden — "
                    "check SEMANTIC_SCHOLAR_API_KEY in .env"
                )
                return None

            logger.error(
                "SemanticScholarConnector: HTTP %d", response.status_code
            )
            return None

        logger.error("SemanticScholarConnector: failed after all retries")
        return None

    @staticmethod
    def _parse_record(record: dict) -> Optional[object]:
        from models.data_classes import CandidateRecord

        try:
            title = (record.get("title") or "").strip()
            if not title:
                return None

            external_ids = record.get("externalIds") or {}
            doi: Optional[str] = external_ids.get("DOI")

            # Prefer PubMed ID for cross-deduplication with PubMed results
            pmid: Optional[str] = external_ids.get("PubMed")
            if pmid:
                pmid = str(pmid)

            year: Optional[int] = record.get("year")

            raw_authors = record.get("authors") or []
            authors: List[str] = [
                a["name"] for a in raw_authors if a.get("name")
            ]

            oa_pdf = record.get("openAccessPdf") or {}
            # store pdf URL in external_id field for FullTextRetriever
            pdf_url: Optional[str] = oa_pdf.get("url")

            return CandidateRecord(
                source_database = "semantic_scholar",
                title           = title,
                abstract        = record.get("abstract") or None,
                doi             = doi,
                pmid            = pmid,
                year            = year,
                authors         = authors,
                # reuse external_id to carry the OA PDF URL downstream
                external_id     = pdf_url,
            )

        except Exception as exc:
            logger.warning("SemanticScholarConnector: failed to parse record: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Smoke test:  python tier1_search/semantic_scholar_connector.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

    from models.data_classes import SearchQuery

    connector = SemanticScholarConnector()

    query = SearchQuery(
        research_question="LLM systematic review screening automation",
        domain_keywords=["large language model", "systematic review", "automation"],
        max_papers_per_db=50,
    )

    print("Running Semantic Scholar smoke test…")
    records = asyncio.run(connector.search(query))
    print(f"Records returned: {len(records)}")
    for r in records[:5]:
        print(f"  [{r.year}] {r.title[:80]}  doi={r.doi}")
    print("Smoke test complete.")
