"""
tier1_search/pubmed_connector.py
=================================
PubMed connector via NCBI E-utilities (Biopython Entrez).

Credentials are read from environment / config.settings:
    PUBMED_API_KEY   — optional; raises rate limit from 3 → 10 req/s
    PUBMED_EMAIL     — required by NCBI policy

Public interface expected by DatabaseConnector:
    PubMedConnector()                     ← no-arg constructor
    await connector.search(query)         ← async, returns List[CandidateRecord]
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import List, Optional

from Bio import Entrez, Medline
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_CHUNK_SIZE   = 500
_MAX_RESULTS  = 9_999
_RATE_LIMIT_S = 0.35   # conservative: 3 req/s without key; 10 req/s with key


def _build_pubmed_query(query) -> str:
    """
    Convert a SearchQuery into a PubMed E-utilities query string.

    Strategy:
      - Use domain_keywords as free-text [TIAB] terms joined with OR
      - Wrap the OR-block in parentheses
      - Append date range filter if present
    """
    keywords = list(dict.fromkeys(kw.strip() for kw in query.domain_keywords if kw.strip()))

    if keywords:
        tiab_terms = " OR ".join(f'"{kw}"[TIAB]' for kw in keywords)
        q = f"({tiab_terms})"
    else:
        q = query.research_question.strip()

    if query.year_range:
        start, end = query.year_range
        q += f' AND ("{start}/01/01"[PDAT]:"{end}/12/31"[PDAT])'

    return q


class PubMedConnector:
    """
    Synchronous PubMed search wrapped in an async interface.
    The blocking Entrez I/O runs in a thread-pool executor.
    """

    def __init__(self) -> None:
        self._api_key = os.getenv("PUBMED_API_KEY", "")
        self._email   = os.getenv("PUBMED_EMAIL", "systematic-review@example.com")

        Entrez.email = self._email
        if self._api_key:
            Entrez.api_key = self._api_key
            logger.info("PubMedConnector: using API key (10 req/s)")
        else:
            logger.info("PubMedConnector: no API key (3 req/s)")

    # ------------------------------------------------------------------
    # Public async interface
    # ------------------------------------------------------------------

    async def search(self, query) -> list:
        """
        Execute PubMed search for *query* and return CandidateRecord list.
        Blocking Entrez calls run in the default thread-pool executor.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._search_sync, query)

    # ------------------------------------------------------------------
    # Synchronous implementation (runs in executor)
    # ------------------------------------------------------------------

    def _search_sync(self, query) -> list:
        pubmed_query = _build_pubmed_query(query)
        max_results  = min(query.max_papers_per_db, _MAX_RESULTS)

        logger.info("PubMedConnector: query='%s'  limit=%d", pubmed_query[:120], max_results)

        try:
            search_handle = Entrez.esearch(
                db      = "pubmed",
                term    = pubmed_query,
                retmax  = max_results,
                sort    = "relevance",
                retmode = "xml",
            )
            search_results = Entrez.read(search_handle)
            search_handle.close()
        except Exception as exc:
            logger.error("PubMedConnector: esearch failed: %s", exc)
            return []

        id_list: list = search_results.get("IdList", [])
        if not id_list:
            logger.info("PubMedConnector: no results for query")
            return []

        logger.info("PubMedConnector: %d IDs retrieved", len(id_list))

        records: list = []
        for start in range(0, len(id_list), _CHUNK_SIZE):
            chunk = id_list[start : start + _CHUNK_SIZE]
            try:
                fetch_handle = Entrez.efetch(
                    db      = "pubmed",
                    id      = chunk,
                    rettype = "medline",
                    retmode = "text",
                )
                medline_records = list(Medline.parse(fetch_handle))
                fetch_handle.close()
            except Exception as exc:
                logger.error("PubMedConnector: efetch failed (chunk %d): %s", start, exc)
                continue

            for rec in medline_records:
                candidate = self._parse_record(rec)
                if candidate:
                    records.append(candidate)

            time.sleep(_RATE_LIMIT_S)

        logger.info("PubMedConnector: returning %d records", len(records))
        return records

    @staticmethod
    def _parse_record(record: dict) -> Optional[object]:
        from models.data_classes import CandidateRecord

        try:
            title = record.get("TI", "").strip()
            if not title:
                return None

            abstract = record.get("AB", "") or ""

            # DOI: prefer AID list, fall back to LID
            doi: Optional[str] = None
            for field in ("AID", "LID"):
                for entry in record.get(field, []):
                    if entry.endswith("[doi]"):
                        doi = entry.replace("[doi]", "").strip()
                        break
                if doi:
                    break

            # PMID
            pmid: Optional[str] = record.get("PMID")
            if pmid:
                pmid = pmid.strip()

            # Year: first token of DP (Date of Publication)
            year: Optional[int] = None
            dp = record.get("DP", "")
            if dp:
                first = dp.split()[0]
                if first.isdigit():
                    year = int(first)

            authors: list = record.get("AU", [])

            return CandidateRecord(
                source_database = "pubmed",
                title           = title,
                abstract        = abstract or None,
                doi             = doi,
                pmid            = pmid,
                year            = year,
                authors         = authors,
            )

        except Exception as exc:
            logger.warning("PubMedConnector: failed to parse record: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Smoke test:  python tier1_search/pubmed_connector.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))

    from models.data_classes import SearchQuery

    connector = PubMedConnector()

    query = SearchQuery(
        research_question='("large language model"[TIAB] OR "LLM"[TIAB]) AND "systematic review"[TIAB]',
        domain_keywords=["large language model", "systematic review", "screening"],
        max_papers_per_db=50,
    )

    print("Running PubMed smoke test…")
    records = asyncio.run(connector.search(query))
    print(f"Records returned: {len(records)}")
    for r in records[:5]:
        print(f"  [{r.year}] {r.title[:80]}  doi={r.doi}")
    print("Smoke test complete.")
