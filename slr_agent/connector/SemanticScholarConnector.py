import time
import logging
import requests
from typing import List, Optional

from connector.BaseConnector import BaseConnector
from model.Paper import Paper

logger = logging.getLogger(__name__)


class SemanticScholarConnector(BaseConnector):

    __BULK_URL: str = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
    __FIELDS: str = "title,abstract,year,citationCount,externalIds,openAccessPdf"
    __BULK_MAX: int = 1000      # S2 bulk endpoint documented hard cap
    __RETRY_WAIT: int = 3       # seconds to wait on 429 before retry

    def __init__(self, apiKey: str):
        super().__init__(apiKey=apiKey, baseUrl="https://api.semanticscholar.org")

    def fetchPapers(self, query: str, maxResults: int) -> List[Paper]:
        # clamp to [1, 1000]
        original = maxResults
        maxResults = max(1, min(maxResults, self.__BULK_MAX))
        if maxResults != original:
            logger.warning(
                "S2 limit clamped %d → %d (bulk endpoint max is %d)",
                original, maxResults, self.__BULK_MAX
            )

        logger.info("S2 search: '%s'  limit=%d", query[:100], maxResults)

        params = {
            "query": query,
            "limit": maxResults,
            "fields": self.__FIELDS,
        }

        # api-key header — confirmed working with S2 API key
        headers = {"api-key": self.apiKey} if self.apiKey else {}

        # single request, one retry on 429
        response = self.__makeRequest(params, headers)
        if response is None:
            return []

        try:
            data = response.json()
        except ValueError:
            logger.error("S2 returned non-JSON response")
            return []

        papers = []
        for item in data.get("data", []):
            paper = self.__parseRecord(item)
            if paper:
                papers.append(paper)

        logger.info("S2 returned %d papers", len(papers))
        return papers

    def __makeRequest(self, params: dict, headers: dict):
        for attempt in range(1, 3):
            try:
                response = requests.get(
                    self.__BULK_URL,
                    params=params,
                    headers=headers,
                    timeout=30
                )
            except requests.exceptions.Timeout:
                logger.error("S2 request timed out (attempt %d)", attempt)
                return None
            except requests.exceptions.RequestException as e:
                logger.error("S2 network error: %s", e)
                return None

            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                wait = self.__RETRY_WAIT * attempt
                logger.warning("S2 rate limit (attempt %d). Waiting %ds...", attempt, wait)
                time.sleep(wait)
                continue
            elif response.status_code == 400:
                logger.error("S2 rejected query (400). Query was: %s", params.get("query", "")[:200])
                return None
            elif response.status_code == 403:
                logger.error(
                    "S2 returned 403 Forbidden. Check SEMANTIC_SCHOLAR_API_KEY in .env"
                )
                return None
            else:
                logger.error("S2 returned HTTP %d", response.status_code)
                return None

        logger.error("S2 failed after all retries")
        return None

    def __parseRecord(self, record: dict) -> Optional[Paper]:
        try:
            title = record.get("title", "")
            if not title or not title.strip():
                return None

            abstract = record.get("abstract", "")
            doi = (record.get("externalIds") or {}).get("DOI")
            year = record.get("year")
            pdfLink = ((record.get("openAccessPdf") or {}).get("url"))

            rawAuthors = record.get("authors", [])
            authors = [a.get("name", "") for a in rawAuthors if a.get("name")]

            return Paper(
                title=title,
                abstract=abstract,
                doi=doi,
                year=year if year else 0,
                source="SemanticScholar",
                pdfLink=pdfLink,
                author=authors
            )

        except Exception as e:
            logger.warning("S2: failed to parse record: %s", e)
            return None


# ─────────────────────────────────────────────────────────────
# DELETE BEFORE PRODUCTION — quick smoke test
# run: python -m module1.connectors.SemanticScholarConnector
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    connector = SemanticScholarConnector(
        apiKey=os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    )

    print("Running Semantic Scholar smoke test...")
    print("Query: LLM systematic review screening")
    print("-" * 50)

    papers = connector.fetchPapers(
        query="LLM systematic review screening automation",
        maxResults=100
    )

    print(f"Papers returned: {len(papers)}")
    print()

    for i, paper in enumerate(papers, 1):
        print(f"[{i}] {paper.title}")
        print(f"     DOI    : {paper.doi}")
        print(f"     Year   : {paper.year}")
        print(f"     Source : {paper.source}")
        print(f"     PDF    : {paper.pdfLink}")
        print(f"     Authors: {paper.author[:2]}")
        print(f"     Abstract: {str(paper.abstract)[:80]}...")
        print()

    print("Smoke test complete.")