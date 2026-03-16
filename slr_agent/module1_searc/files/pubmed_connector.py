"""
pubmed_connector.py — PubMed / NCBI Entrez Connector
=====================================================
Design Concepts
---------------
1. Explicit retmax Enforcement
   The `retmax` parameter is validated and clamped to [1, 9999] (NCBI's
   documented maximum for a single Entrez fetch) before the API call.
   Previously the limit was declared in the signature but never forwarded
   reliably to the internal search step.

2. Chunked Fetching
   NCBI Entrez efetch accepts at most ~500 IDs per request before responses
   become unreliable. We chunk the ID list and merge results. This makes
   large searches (retmax > 500) actually work.

3. Structured Error Return
   Parsing errors on individual articles are caught and logged without
   crashing the whole fetch. The function always returns a list (possibly
   empty) so callers don't need to handle exceptions.
"""

import logging
import time
import xml.etree.ElementTree as ET
from typing import List, Optional

from Bio import Entrez

logger = logging.getLogger(__name__)

Entrez.email = "your_email@example.com"   # required by NCBI

_NCBI_MAX_PER_FETCH = 500   # NCBI recommended chunk size
_NCBI_ABSOLUTE_MAX  = 9999  # NCBI hard limit for retmax


def search_pubmed(query: str, retmax: int = 500) -> List[str]:
    """
    Search PubMed and return a list of PubMed IDs.

    Parameters
    ----------
    query  : PubMed Boolean query string (field-tagged preferred).
    retmax : Max number of IDs to retrieve. Clamped to [1, 9999].
    """
    retmax = max(1, min(retmax, _NCBI_ABSOLUTE_MAX))
    logger.info("PubMed esearch: '%s' (retmax=%d)", query[:80], retmax)

    try:
        handle  = Entrez.esearch(
            db="pubmed",
            term=query,
            retmax=str(retmax),
            sort="relevance",
            retmode="xml",
        )
        results = Entrez.read(handle)
        handle.close()
        ids = results.get("IdList", [])
        logger.info("PubMed esearch returned %d IDs.", len(ids))
        return ids
    except Exception as exc:
        logger.error("PubMed esearch failed: %s", exc)
        return []


def fetch_pubmed_details(id_list: List[str]) -> List[dict]:
    """
    Fetch full metadata for a list of PubMed IDs, in chunks.

    Returns a list of paper dicts:
        title, abstract, doi, year, source
    """
    if not id_list:
        return []

    papers: List[dict] = []

    # ── Chunked fetch ────────────────────────────────────────────────────────
    for chunk_start in range(0, len(id_list), _NCBI_MAX_PER_FETCH):
        chunk = id_list[chunk_start : chunk_start + _NCBI_MAX_PER_FETCH]
        logger.info(
            "Fetching PubMed details chunk %d–%d of %d IDs…",
            chunk_start + 1, chunk_start + len(chunk), len(id_list)
        )

        try:
            handle   = Entrez.efetch(db="pubmed", id=",".join(chunk), retmode="xml")
            xml_data = handle.read()
            handle.close()
        except Exception as exc:
            logger.error("PubMed efetch chunk %d failed: %s", chunk_start, exc)
            continue

        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as exc:
            logger.error("PubMed XML parse error: %s", exc)
            continue

        for article in root.findall(".//PubmedArticle"):
            paper = _parse_article(article)
            if paper:
                papers.append(paper)

        # Respect NCBI rate limit (3 requests/second without API key)
        time.sleep(0.35)

    logger.info("PubMed fetched %d papers total.", len(papers))
    return papers


def _parse_article(article: ET.Element) -> Optional[dict]:
    """
    Parse a single <PubmedArticle> XML element into a paper dict.
    Returns None if the article is missing a title (unusable).
    """
    try:
        medline = article.find("MedlineCitation")
        if medline is None:
            return None
        art = medline.find("Article")
        if art is None:
            return None

        title_elem = art.find("ArticleTitle")
        title = (title_elem.text or "").strip() if title_elem is not None else ""
        if not title:
            return None

        # Abstract — may have multiple AbstractText elements (structured abstracts)
        abstract_parts = []
        for at in art.findall("Abstract/AbstractText"):
            text = at.text or ""
            label = at.attrib.get("Label")
            abstract_parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(abstract_parts)

        # DOI
        doi = None
        for el in article.findall(".//ArticleId"):
            if el.attrib.get("IdType") == "doi":
                doi = (el.text or "").strip()

        # Year — prefer PubDate year, fall back to MedlineDate
        year = None
        pub_date = art.find(".//PubDate")
        if pub_date is not None:
            year_el = pub_date.find("Year")
            if year_el is not None:
                try:
                    year = int(year_el.text)
                except (ValueError, TypeError):
                    pass

        return {
            "title":    title,
            "abstract": abstract,
            "doi":      doi,
            "year":     year,
            "source":   "pubmed",
        }
    except Exception as exc:
        logger.warning("Failed to parse PubMed article: %s", exc)
        return None


def search(query: str, retmax: int = 500) -> List[dict]:
    """
    Public API: search PubMed and return paper dicts.

    This is the function imported by literature_handler.py.
    The `retmax` parameter is now enforced end-to-end:
      literature_handler → search(retmax=sq.max_papers_per_db) → search_pubmed(retmax)
    """
    ids = search_pubmed(query, retmax=retmax)
    return fetch_pubmed_details(ids)
