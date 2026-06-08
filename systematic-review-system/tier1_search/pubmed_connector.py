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
import xml.etree.ElementTree as ET
from typing import List, Optional

from Bio import Entrez, Medline
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_CHUNK_SIZE   = 500
_MAX_RESULTS  = 9_999
_RATE_LIMIT_S = 0.35   # conservative: 3 req/s without key; 10 req/s with key


def _tiab_term(phrase: str) -> str:
    """
    Format a single phrase as a PubMed TIAB term.

    Phrases of 1–3 words get exact-phrase quoting: "sugar tax"[TIAB]
    Phrases longer than 3 words must NOT be quoted (quoting kills recall);
    they are split into individual content words (stopwords dropped) joined by AND.
    """
    words = phrase.split()
    if len(words) <= 3:
        return f'"{phrase}"[TIAB]'
    from tier1_search.query_builder import _STOPWORDS
    content_words = [w for w in words if w.lower() not in _STOPWORDS and len(w) >= 3]
    if not content_words:
        content_words = words  # nothing to drop — keep all
    return " AND ".join(f"{w}[TIAB]" for w in content_words)


def _build_pubmed_query(query) -> str:
    """
    Convert a SearchQuery into a structured PubMed E-utilities query string.

    If query.pubmed_query_override is set (populated by LLMQueryBuilder), it is
    returned directly — this is the preferred path for non-clinical protocols.

    Rule-based fallback (Strategy 2-group AND):
      1. Group A — intervention phrases + any refinement-added domain_keywords.
      2. Group B — outcome phrases; falls back to comparison phrases if empty.
      Phrases of > 3 words are never wrapped in quotes (Rule of 3 — long exact
      phrases return 0 results against real databases).
    """
    if query.pubmed_query_override:
        return query.pubmed_query_override

    from tier1_search.query_builder import _extract_phrases

    # --- Group A: intervention phrases + refinement-added domain keywords -----------
    int_phrases: list[str] = _extract_phrases(query.intervention or "")

    _pico_phrase_lower: set[str] = set()
    for _fv in (query.population, query.intervention, query.outcome, query.comparison):
        for _p in _extract_phrases(_fv or ""):
            _pico_phrase_lower.add(_p.lower())

    extra_kw: list[str] = [
        kw.strip() for kw in (query.domain_keywords or [])
        if kw.strip() and kw.strip().lower() not in _pico_phrase_lower
    ]
    group_a: list[str] = list(dict.fromkeys(int_phrases + extra_kw))

    # --- Group B: outcome phrases (target conditions) --------------------------------
    group_b: list[str] = _extract_phrases(query.outcome or "")
    if not group_b:
        group_b = _extract_phrases(query.comparison or "")

    # --- Assemble query --------------------------------------------------------------
    blocks: list[str] = []
    for group in (group_a, group_b):
        if group:
            tiab = " OR ".join(_tiab_term(p) for p in group)
            blocks.append(f"({tiab})")

    if blocks:
        q = " AND ".join(blocks)
    elif query.domain_keywords:
        keywords = list(dict.fromkeys(kw.strip() for kw in query.domain_keywords if kw.strip()))
        tiab_terms = " OR ".join(_tiab_term(kw) for kw in keywords)
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

    # ------------------------------------------------------------------
    # Direct PMID fetch
    # ------------------------------------------------------------------

    async def fetch_by_pmids(
        self,
        pmids: list[str],
        batch_size: int = 200,
    ) -> dict[str, dict]:
        """
        Fetch title and abstract for a list of PMIDs via PubMed efetch.
        Returns dict of {pmid_str: {"title": str, "abstract": str}}.
        PMIDs with no result are silently omitted from the dict.
        """
        loop = asyncio.get_running_loop()
        results: dict[str, dict] = {}

        for start in range(0, len(pmids), batch_size):
            batch = pmids[start : start + batch_size]
            try:
                # Biopython Entrez already carries the API key set in __init__.
                # efetch with retmode="xml" returns a bytes handle.
                def _fetch(b: list[str] = batch) -> bytes:
                    handle = Entrez.efetch(
                        db="pubmed",
                        id=",".join(b),
                        rettype="abstract",
                        retmode="xml",
                    )
                    data = handle.read()
                    handle.close()
                    return data

                xml_bytes = await loop.run_in_executor(None, _fetch)
                root = ET.fromstring(xml_bytes)

                for article in root.findall(".//PubmedArticle"):
                    pmid_el = article.find("./MedlineCitation/PMID")
                    if pmid_el is None:
                        continue
                    pmid_str = (pmid_el.text or "").strip()
                    if not pmid_str:
                        continue

                    title_el = article.find("./MedlineCitation/Article/ArticleTitle")
                    title = (
                        "".join(title_el.itertext()).strip()
                        if title_el is not None
                        else ""
                    )

                    abstract_els = article.findall(
                        "./MedlineCitation/Article/Abstract/AbstractText"
                    )
                    abstract = " ".join(
                        "".join(el.itertext()) for el in abstract_els
                    ).strip()

                    results[pmid_str] = {"title": title, "abstract": abstract}

            except Exception as exc:
                logger.warning(
                    "fetch_by_pmids: batch [%d:%d] failed: %s",
                    start,
                    start + batch_size,
                    exc,
                )

            if start + batch_size < len(pmids):
                await asyncio.sleep(0.11)

        return results

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
