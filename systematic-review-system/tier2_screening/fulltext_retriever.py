"""
tier2_screening/fulltext_retriever.py
=======================================
Full-text retrieval from open-access sources.

For each candidate the following sources are tried in order:
  1. Unpaywall  — downloads best open-access PDF
  2. Europe PMC — fetches full-text XML when available
  3. PubMed Central (eFetch) — fetches XML via PMC ID converted from PMID

Files are saved under data/reviews/{review_id}/documents/{record_id}/.
Concurrency is bounded by asyncio.Semaphore(5).

Environment variables
---------------------
UNPAYWALL_EMAIL   (required for Unpaywall polite pool)
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

from models.data_classes import AbstractContext, CandidateRecord, RetrievalResult

load_dotenv()

logger = logging.getLogger(__name__)

_CONCURRENCY      = 5
_REQUEST_TIMEOUT  = 30    # seconds
_DOWNLOAD_TIMEOUT = 120   # seconds for large PDF downloads

# API URL templates
_UNPAYWALL_URL      = "https://api.unpaywall.org/v2/{doi}?email={email}"
_EUROPE_PMC_URL     = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    "?query=DOI:{doi}&format=json&resultType=core"
)
_EUROPE_PMC_XML_URL = (
    "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{pmcid}/fullTextXML"
)
_ELINK_URL          = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
    "?dbfrom=pubmed&db=pmc&id={pmid}&retmode=json"
)
_EFETCH_URL         = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    "?db=pmc&id={pmcid}&rettype=xml&retmode=xml"
)


class FullTextRetriever:
    """
    Retrieves full-text documents for a list of abstract-screened candidates.

    Parameters
    ----------
    review_id : str
        Used to build the storage path: data/reviews/{review_id}/documents/
    """

    def __init__(self, review_id: str) -> None:
        self._review_id = review_id
        self._email     = os.getenv("UNPAYWALL_EMAIL", "")
        self._base_dir  = Path("data") / "reviews" / review_id / "documents"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def retrieve_batch(
        self,
        contexts:   List[AbstractContext],
        candidates: List[CandidateRecord],
    ) -> List[RetrievalResult]:
        """
        Retrieve full text for each candidate with an AbstractContext.

        Processes candidates in descending order of abstract_confidence so
        that the highest-priority papers are retrieved first.
        """
        sorted_contexts = sorted(
            contexts,
            key=lambda c: c.abstract_confidence,
            reverse=True,
        )
        candidate_map: Dict[str, CandidateRecord] = {c.record_id: c for c in candidates}
        sem = asyncio.Semaphore(_CONCURRENCY)

        connector = aiohttp.TCPConnector(limit=_CONCURRENCY)
        timeout   = aiohttp.ClientTimeout(
            total=_DOWNLOAD_TIMEOUT,
            connect=_REQUEST_TIMEOUT,
        )

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:

            async def _bounded(ctx: AbstractContext) -> RetrievalResult:
                candidate = candidate_map.get(ctx.record_id)
                if candidate is None:
                    logger.warning(
                        "FullTextRetriever: no candidate found for record_id=%s",
                        ctx.record_id,
                    )
                    return RetrievalResult(
                        record_id      = ctx.record_id,
                        success        = False,
                        failure_reason = "candidate_not_found",
                    )
                async with sem:
                    return await self._retrieve_one(session, candidate)

            results = await asyncio.gather(*[_bounded(ctx) for ctx in sorted_contexts])

        successes = sum(1 for r in results if r.success)
        logger.info(
            "FullTextRetriever: %d/%d documents retrieved successfully",
            successes,
            len(results),
        )
        return list(results)

    # ------------------------------------------------------------------
    # Internal: per-candidate orchestration
    # ------------------------------------------------------------------

    async def _retrieve_one(
        self,
        session:   aiohttp.ClientSession,
        candidate: CandidateRecord,
    ) -> RetrievalResult:
        dest_dir = self._base_dir / candidate.record_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        doi  = (candidate.doi  or "").strip()
        pmid = (candidate.pmid or "").strip()

        # Source 0: direct OA PDF URL from Semantic Scholar metadata (stored in external_id)
        oa_url = (candidate.external_id or "").strip()
        if oa_url.startswith("http"):
            result = await self._try_direct_pdf(session, candidate, oa_url, dest_dir)
            if result.success:
                return result

        # Source 1: Unpaywall (PDF)
        if doi:
            result = await self._try_unpaywall(session, candidate, doi, dest_dir)
            if result.success:
                return result

        # Source 2: Europe PMC (XML)
        if doi:
            result = await self._try_europe_pmc(session, candidate, doi, dest_dir)
            if result.success:
                return result

        # Source 3: PubMed Central eFetch (XML)
        if pmid:
            result = await self._try_pubmed_central(session, candidate, pmid, dest_dir)
            if result.success:
                return result

        logger.debug(
            "FullTextRetriever: all sources failed for record_id=%s (doi=%r pmid=%r)",
            candidate.record_id,
            doi or None,
            pmid or None,
        )
        return RetrievalResult(
            record_id      = candidate.record_id,
            success        = False,
            failure_reason = "all_sources_failed",
        )

    # ------------------------------------------------------------------
    # Source 0: direct OA PDF URL (from Semantic Scholar metadata)
    # ------------------------------------------------------------------

    async def _try_direct_pdf(
        self,
        session:   aiohttp.ClientSession,
        candidate: CandidateRecord,
        url:       str,
        dest_dir:  Path,
    ) -> RetrievalResult:
        pdf_path = dest_dir / "fulltext.pdf"
        try:
            await self._download_file(session, url, pdf_path)
        except Exception as exc:
            logger.debug(
                "FullTextRetriever: direct PDF download failed for %s: %s",
                candidate.record_id, exc,
            )
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = f"direct_pdf_error: {exc}",
            )

        logger.info(
            "FullTextRetriever: retrieved PDF via direct URL for %s",
            candidate.record_id,
        )
        return RetrievalResult(
            record_id        = candidate.record_id,
            success          = True,
            pdf_path         = str(pdf_path),
            retrieval_source = "direct_url",
        )

    # ------------------------------------------------------------------
    # Source 1: Unpaywall
    # ------------------------------------------------------------------

    async def _try_unpaywall(
        self,
        session:   aiohttp.ClientSession,
        candidate: CandidateRecord,
        doi:       str,
        dest_dir:  Path,
    ) -> RetrievalResult:
        if not self._email:
            logger.debug("FullTextRetriever: UNPAYWALL_EMAIL not set, skipping Unpaywall")
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = "unpaywall_email_not_configured",
            )

        url = _UNPAYWALL_URL.format(doi=doi, email=self._email)
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return RetrievalResult(
                        record_id      = candidate.record_id,
                        success        = False,
                        failure_reason = f"unpaywall_http_{resp.status}",
                    )
                data = await resp.json(content_type=None)
        except Exception as exc:
            logger.debug("FullTextRetriever: Unpaywall request failed: %s", exc)
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = f"unpaywall_error: {exc}",
            )

        oa_locations = data.get("oa_locations") or []
        pdf_url = self._best_pdf_url(data, oa_locations)
        if not pdf_url:
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = "unpaywall_no_oa_pdf",
            )

        pdf_path = dest_dir / "fulltext.pdf"
        try:
            await self._download_file(session, pdf_url, pdf_path)
        except Exception as exc:
            logger.debug("FullTextRetriever: Unpaywall download failed: %s", exc)
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = f"unpaywall_download_error: {exc}",
            )

        logger.info(
            "FullTextRetriever: retrieved PDF via Unpaywall for %s",
            candidate.record_id,
        )
        return RetrievalResult(
            record_id        = candidate.record_id,
            success          = True,
            pdf_path         = str(pdf_path),
            retrieval_source = "unpaywall",
        )

    @staticmethod
    def _best_pdf_url(data: dict, oa_locations: list) -> Optional[str]:
        """Return the most direct OA PDF URL from an Unpaywall response.

        Only returns actual PDF URLs (url_for_pdf).  Landing page URLs are
        intentionally excluded because pdfminer cannot parse HTML responses.
        """
        best = data.get("best_oa_location") or {}
        if best.get("url_for_pdf"):
            return best["url_for_pdf"]
        for loc in oa_locations:
            if loc.get("url_for_pdf"):
                return loc["url_for_pdf"]
        return None

    # ------------------------------------------------------------------
    # Source 2: Europe PMC
    # ------------------------------------------------------------------

    async def _try_europe_pmc(
        self,
        session:   aiohttp.ClientSession,
        candidate: CandidateRecord,
        doi:       str,
        dest_dir:  Path,
    ) -> RetrievalResult:
        search_url = _EUROPE_PMC_URL.format(doi=doi)
        try:
            async with session.get(search_url) as resp:
                if resp.status != 200:
                    return RetrievalResult(
                        record_id      = candidate.record_id,
                        success        = False,
                        failure_reason = f"europepmc_search_http_{resp.status}",
                    )
                data = await resp.json(content_type=None)
        except Exception as exc:
            logger.debug("FullTextRetriever: Europe PMC search failed: %s", exc)
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = f"europepmc_search_error: {exc}",
            )

        results = (data.get("resultList") or {}).get("result") or []
        if not results:
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = "europepmc_not_found",
            )

        hit = results[0]
        if not hit.get("fullTextAvailable"):
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = "europepmc_no_fulltext",
            )

        source = hit.get("source", "MED")
        pmcid  = hit.get("pmcid") or hit.get("id", "")
        if not pmcid:
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = "europepmc_no_pmcid",
            )

        xml_url  = _EUROPE_PMC_XML_URL.format(source=source, pmcid=pmcid)
        xml_path = dest_dir / "fulltext.xml"
        try:
            await self._download_file(session, xml_url, xml_path)
        except Exception as exc:
            logger.debug("FullTextRetriever: Europe PMC XML download failed: %s", exc)
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = f"europepmc_download_error: {exc}",
            )

        logger.info(
            "FullTextRetriever: retrieved XML via Europe PMC for %s",
            candidate.record_id,
        )
        return RetrievalResult(
            record_id        = candidate.record_id,
            success          = True,
            xml_path         = str(xml_path),
            retrieval_source = "europe_pmc",
        )

    # ------------------------------------------------------------------
    # Source 3: PubMed Central
    # ------------------------------------------------------------------

    async def _try_pubmed_central(
        self,
        session:   aiohttp.ClientSession,
        candidate: CandidateRecord,
        pmid:      str,
        dest_dir:  Path,
    ) -> RetrievalResult:
        pmcid = await self._pmid_to_pmcid(session, pmid)
        if not pmcid:
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = "pmc_no_pmcid_for_pmid",
            )

        xml_url  = _EFETCH_URL.format(pmcid=pmcid)
        xml_path = dest_dir / "fulltext.xml"
        try:
            await self._download_file(session, xml_url, xml_path)
        except Exception as exc:
            logger.debug("FullTextRetriever: PMC eFetch download failed: %s", exc)
            return RetrievalResult(
                record_id      = candidate.record_id,
                success        = False,
                failure_reason = f"pmc_download_error: {exc}",
            )

        logger.info(
            "FullTextRetriever: retrieved XML via PubMed Central for %s",
            candidate.record_id,
        )
        return RetrievalResult(
            record_id        = candidate.record_id,
            success          = True,
            xml_path         = str(xml_path),
            retrieval_source = "pubmed_central",
        )

    async def _pmid_to_pmcid(
        self,
        session: aiohttp.ClientSession,
        pmid:    str,
    ) -> Optional[str]:
        """Convert a PubMed ID to a PMC ID via Entrez elink."""
        url = _ELINK_URL.format(pmid=pmid)
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
        except Exception as exc:
            logger.debug("FullTextRetriever: elink request failed: %s", exc)
            return None

        # Navigate Entrez elink JSON: linksets[].linksetdbs[{dbto:"pmc"}].links[]
        for ls in data.get("linksets") or []:
            for lsdb in ls.get("linksetdbs") or []:
                if lsdb.get("dbto") == "pmc":
                    ids = lsdb.get("links") or []
                    if ids:
                        return str(ids[0])
        return None

    # ------------------------------------------------------------------
    # Shared file-download helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _download_file(
        session: aiohttp.ClientSession,
        url:     str,
        dest:    Path,
    ) -> None:
        """Stream *url* to *dest*.  Raises aiohttp.ClientResponseError on HTTP error."""
        async with session.get(url) as resp:
            resp.raise_for_status()
            with dest.open("wb") as fh:
                async for chunk in resp.content.iter_chunked(65536):
                    fh.write(chunk)
