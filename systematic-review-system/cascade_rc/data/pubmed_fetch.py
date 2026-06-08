"""Async PubMed abstract fetcher with per-PMID caching and rate limiting."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import aiohttp
import tenacity

logger = logging.getLogger(__name__)

_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
_BATCH_SIZE = 200
_RATE_WITH_KEY = 10.0   # requests/second
_RATE_NO_KEY = 3.0      # requests/second


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

def _strip_markup(text: str) -> str:
    """Remove residual XML/HTML tags and normalise whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).strip()


def _parse_pubmed_article(article_el: ET.Element) -> dict[str, str | list[str]] | None:
    """Extract title, abstract, and MeSH terms from a single <PubmedArticle>."""
    medline = article_el.find("MedlineCitation")
    if medline is None:
        return None

    pmid_el = medline.find("PMID")
    pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""
    if not pmid:
        return None

    art = medline.find("Article")
    if art is None:
        return None

    title_el = art.find("ArticleTitle")
    title = _strip_markup(ET.tostring(title_el, encoding="unicode", method="text")) if title_el is not None else ""

    abstract_texts: list[str] = []
    abstract_el = art.find("Abstract")
    if abstract_el is not None:
        for text_el in abstract_el.findall("AbstractText"):
            chunk = ET.tostring(text_el, encoding="unicode", method="text").strip()
            if chunk:
                abstract_texts.append(chunk)
    abstract = " ".join(abstract_texts) if abstract_texts else ""

    mesh: list[str] = []
    for mh in medline.findall(".//MeshHeading/DescriptorName"):
        if mh.text:
            mesh.append(mh.text.strip())

    return {"pmid": pmid, "title": title, "abstract": abstract, "mesh": mesh}


# ---------------------------------------------------------------------------
# Single-batch fetch with tenacity retry
# ---------------------------------------------------------------------------

def _make_retry() -> tenacity.Retrying:
    return tenacity.Retrying(
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=60),
        stop=tenacity.stop_after_attempt(5),
        retry=tenacity.retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=True,
    )


async def _fetch_batch(
    session: aiohttp.ClientSession,
    pmids: list[str],
    email: str,
    api_key: str | None,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, str | list[str]]]:
    """Fetch and parse one batch of PMIDs; returns list of article dicts."""
    params: dict[str, str] = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
        "email": email,
    }
    if api_key:
        params["api_key"] = api_key

    async with semaphore:
        for attempt in _make_retry():
            with attempt:
                async with session.get(_EFETCH_URL, params=params, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    resp.raise_for_status()
                    xml_text = await resp.text(encoding="utf-8")

    results: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
        for article_el in root.findall("PubmedArticle"):
            rec = _parse_pubmed_article(article_el)
            if rec:
                results.append(rec)
    except ET.ParseError as exc:
        logger.warning("XML parse error for batch %s…: %s", pmids[:3], exc)
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_abstracts(
    pmids: list[str],
    email: str,
    api_key: str | None = None,
    cache_dir: Path | None = None,
) -> dict[str, dict[str, str | list[str]]]:
    """Fetch PubMed abstracts for *pmids* with per-PMID JSON caching.

    Returns a mapping pmid → {"title": str, "abstract": str, "mesh": list[str]}.
    Withdrawn PMIDs (empty title and abstract) are stored in cache but excluded
    from the return value.
    """
    if cache_dir is None:
        cache_dir = Path("artefacts/cascade_rc/data/pubmed")
    cache_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, dict] = {}
    missing: list[str] = []

    for pmid in pmids:
        cached = cache_dir / f"{pmid}.json"
        if cached.exists():
            try:
                result[pmid] = json.loads(cached.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                missing.append(pmid)
        else:
            missing.append(pmid)

    if not missing:
        return result

    rate = _RATE_WITH_KEY if api_key else _RATE_NO_KEY
    # Semaphore set to 1 so we control concurrency through inter-batch sleep
    semaphore = asyncio.Semaphore(1)
    interval = 1.0 / rate

    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        batches = [missing[i : i + _BATCH_SIZE] for i in range(0, len(missing), _BATCH_SIZE)]
        for idx, batch in enumerate(batches):
            if idx > 0:
                await asyncio.sleep(interval)
            try:
                articles = await _fetch_batch(session, batch, email, api_key, semaphore)
            except Exception as exc:
                logger.warning("Batch %d/%d failed after retries: %s", idx + 1, len(batches), exc)
                articles = []

            for rec in articles:
                pmid = rec["pmid"]
                rec_clean: dict[str, str | list[str]] = {
                    "title": rec.get("title", ""),
                    "abstract": rec.get("abstract", ""),
                    "mesh": rec.get("mesh", []),
                }
                (cache_dir / f"{pmid}.json").write_text(
                    json.dumps(rec_clean, ensure_ascii=False), encoding="utf-8"
                )
                result[pmid] = rec_clean

    return result
