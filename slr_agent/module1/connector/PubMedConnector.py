import time
import logging
from typing import List, Optional

from Bio import Entrez, Medline

from module1.connector.BaseConnector import BaseConnector
from module1.model.Paper import Paper

logger = logging.getLogger(__name__)


class PubMedConnector(BaseConnector):

    __CHUNK_SIZE: int = 500
    __MAX_RESULTS: int = 9999
    __RATE_LIMIT_WAIT: float = 0.35

    def __init__(self, apiKey: str, email: str):
        super().__init__(apiKey="default", baseUrl="https://eutils.ncbi.nlm.nih.gov")
        self.__email: str = email
        Entrez.email = self.__email
        if apiKey:
            Entrez.api_key = apiKey

    def fetchPapers(self, query: str, maxResults: int) -> List[Paper]:
        papers: List[Paper] = []

        if not query or not query.strip():
            logger.warning("PubMed: empty query provided")
            return papers

        if maxResults <= 0:
            logger.warning("PubMed: invalid maxResults %d", maxResults)
            return papers

        maxResults = max(1, min(maxResults, self.__MAX_RESULTS))

        try:
            searchHandle = Entrez.esearch(
                db="pubmed",
                term=query,
                retmax=maxResults,
                sort="relevance",
                retmode="xml"
            )
            searchResults = Entrez.read(searchHandle)
            searchHandle.close()

            idList = searchResults.get("IdList", [])
            if not idList:
                logger.info("PubMed: no results for query: %s", query[:50])
                return papers

            logger.info("PubMed: found %d IDs", len(idList))

            for i in range(0, len(idList), self.__CHUNK_SIZE):
                chunk = idList[i:i + self.__CHUNK_SIZE]

                fetchHandle = Entrez.efetch(
                    db="pubmed",
                    id=chunk,
                    rettype="medline",
                    retmode="text"
                )
                records = list(Medline.parse(fetchHandle))
                fetchHandle.close()

                for record in records:
                    paper = self.__parseRecord(record)
                    if paper:
                        papers.append(paper)

                time.sleep(self.__RATE_LIMIT_WAIT)

            logger.info("PubMed: fetched %d papers total", len(papers))
            return papers

        except Exception as e:
            logger.error("PubMed fetch failed: %s", e)
            return papers

    def __parseRecord(self, record: dict) -> Optional[Paper]:
        try:
            title = record.get("TI", "")
            if not title or not title.strip():
                return None

            abstract = record.get("AB", "")

            doi = None
            if "AID" in record:
                for aid in record["AID"]:
                    if aid.endswith("[doi]"):
                        doi = aid.replace("[doi]", "").strip()
                        break
            if not doi and "LID" in record:
                for lid in record["LID"]:
                    if lid.endswith("[doi]"):
                        doi = lid.replace("[doi]", "").strip()
                        break

            year = None
            if "DP" in record:
                dp = record["DP"]
                if dp:
                    year_str = dp.split()[0]
                    if year_str.isdigit():
                        year = int(year_str)

            authors: List[str] = record.get("AU", [])

            return Paper(
                title=title,
                abstract=abstract,
                doi=doi,
                year=year if year else 0,
                source="PubMed",
                pdfLink=None,
                author=authors
            )

        except Exception as e:
            logger.warning("PubMed: failed to parse record: %s", e)
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

    connector = PubMedConnector(
        apiKey=os.getenv("PUBMED_API_KEY", ""),
        email=os.getenv("PUBMED_EMAIL", "")
    )

    print("Running PubMed smoke test...")
    print("Query: LLM systematic review screening")
    print("-" * 50)

    papers = connector.fetchPapers(
        query='("large language model"[TIAB] OR "LLM"[TIAB]) AND ("systematic review"[TIAB])',
        maxResults=100
    )

    print(f"Papers returned: {len(papers)}")
    print()

    for i, paper in enumerate(papers, 1):
        print(f"[{i}] {paper.title}")
        print(f"     DOI    : {paper.doi}")
        print(f"     Year   : {paper.year}")
        print(f"     Source : {paper.source}")
        print(f"     Authors: {paper.author[:2]}")
        print(f"     Abstract: {str(paper.abstract)[:80]}...")
        print()

    print("Smoke test complete.")

    import time
import logging
import requests
from typing import List, Optional
from module1.connector.BaseConnector import BaseConnector
from module1.model.Paper import Paper

logger = logging.getLogger(__name__)


class SemanticScholarConnector(BaseConnector):

    __BULK_URL: str = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
    __FIELDS: str = "title,abstract,year,citationCount,externalIds,openAccessPdf"
    __BULK_MAX: int = 1000      # S2 bulk endpoint documented hard cap
    __RETRY_WAIT: int = 3       # seconds to wait on 429 before retry

    def __init__(self, apiKey: str):
        super().__init__(apiKey=apiKey, baseUrl="https://api.semanticscholar.org")

    def fetchPapers(self, query: str, maxResults: int) -> List[Paper]:
        original = maxResults
        maxResults = max(1, min(maxResults, self.__BULK_MAX))
        if maxResults != original:
            logger.warning(
                "S2 limit clamped %d → %d (bulk endpoint max is %d)",
                original, maxResults, self.__BULK_MAX
            )

        logger.info("S2 full query (%d chars): '%s'  limit=%d", len(query), query, maxResults)
        
        params = {
            "query": query,
            "limit": maxResults,
            "fields": self.__FIELDS,
        }
        headers = {"api-key": self.apiKey} if self.apiKey else {}

        response = self.__makeRequest(params, headers)
        if response is None:
            return []

        try:
            data = response.json()
            logger.info("S2 raw response keys: %s", list(data.keys()))
            logger.info("S2 total field: %s", data.get('total'))
            logger.info("S2 data length: %d", len(data.get('data', [])))
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
                year=year if year else None,
                source="SemanticScholar",
                pdfLink=pdfLink,
                author=authors
            )

        except Exception as e:
            logger.warning("S2: failed to parse record: %s", e)
            return None


# ─────────────────────────────────────────────────────────────
# DELETE BEFORE PRODUCTION — quick smoke test
# run: python -m module1.connector.SemanticScholarConnector
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


2026-04-20 12:18:47,706 [INFO] tier2_screening.fulltext_retriever: FullTextRetriever: 66/120 documents retrieved successfully
2026-04-20 12:18:54,887 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for f3d924ae-46dd-4caa-a608-03c563a634e6 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:18:56,005 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/5a28dc7e-0b3f-43a5-ad8e-2ef89f4450b7/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:18:56,006 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 5a28dc7e-0b3f-43a5-ad8e-2ef89f4450b7 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:18:57,677 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 4b7f6915-4b15-4e4d-8ca2-d789a69d85ae (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:18:57,678 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/7f307c60-97ca-4585-982e-e6c8166073cb/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:18:57,678 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 7f307c60-97ca-4585-982e-e6c8166073cb (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:18:57,678 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/9fd62414-8fe6-4d87-b408-e5d70dff3953/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:18:57,678 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 9fd62414-8fe6-4d87-b408-e5d70dff3953 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:18:57,678 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/20b7e896-4283-4142-8f8c-e86c03154bad/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:18:57,678 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 20b7e896-4283-4142-8f8c-e86c03154bad (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:18:57,678 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/9073a457-050e-4e21-85ad-63274e8919f3/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:18:57,678 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 9073a457-050e-4e21-85ad-63274e8919f3 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:01,790 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/ba1d27b3-e948-4733-9b43-de04f761ce29/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:19:01,791 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for ba1d27b3-e948-4733-9b43-de04f761ce29 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:01,874 [WARNING] pdfminer.pdfpage: The PDF <_io.BufferedReader name='data/reviews/ai_in_education_systematic_review/documents/91fae105-5fbb-4ef9-b1a4-ee78c398a07c/fulltext.pdf'> contains a metadata field indicating that it should not allow text extraction. Ignoring this field and proceeding. Use the check_extractable if you want to raise an error in this case
2026-04-20 12:19:08,383 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 187c58e0-0909-4a50-a992-196c2d3581e9 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:11,916 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/7a4de437-3cf5-424c-94f9-3e7539b82f75/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:19:11,916 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 7a4de437-3cf5-424c-94f9-3e7539b82f75 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:15,995 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 7ad6682e-92a0-43e2-af89-47cfef07ad68 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:22,851 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 5109d095-ac27-414f-b710-cf831e5a8047 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:29,243 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/f2abaead-c588-44be-91a2-9fed3b7ddcda/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:19:29,243 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for f2abaead-c588-44be-91a2-9fed3b7ddcda (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:37,895 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for de9bb6e6-d302-462f-9716-dbae30dd5baf (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:42,186 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 8e086bf7-bd8a-4e68-b1bc-2ad70e84261d (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:42,188 [WARNING] tier2_screening.document_parser: DocumentParser: pdfminer failed on data/reviews/ai_in_education_systematic_review/documents/1e0d94ad-0b57-4ed2-bdc2-bc78f519b8a9/fulltext.pdf: No /Root object! - Is this really a PDF?
2026-04-20 12:19:42,188 [WARNING] tier2_screening.document_parser: DocumentParser: low parsing quality for 1e0d94ad-0b57-4ed2-bdc2-bc78f519b8a9 (no METHODS or RESULTS section found, format=pdf)
2026-04-20 12:19:43,055 [INFO] orchestrators.screening_orchestrator: ScreeningOrchestrator: parsed 66/66 documents
2026-04-20 12:19:48,896 [INFO] httpx: HTTP Request: POST https://inference.mlmp.ti.bfh.ch/api/v1/chat/completions "HTTP/1.1 200 OK"
2026-04-20 12:27:21,826 [INFO] tier2_screening.decision_engine: DecisionEngine: 66 total — include=51 exclude=0 uncertain=15
2026-04-20 12:27:21,829 [INFO] orchestrators.main_orchestrator: MainOrchestrator: Phase 2 complete — include=51 exclude=0 uncertain=15
2026-04-20 12:27:21,829 [INFO] orchestrators.main_orchestrator: MainOrchestrator: Phase 3 — Data extraction (51 documents)
2026-04-20 12:37:40,528 [INFO] tier3_synthesis.quality_assessor: QualityAssessor: assessed 51 documents
2026-04-20 12:37:40,531 [INFO] tier3_synthesis.prisma_reporter: PRISMAReporter: flow diagram saved to data/reports/prisma_flow.md
2026-04-20 12:37:42,219 [INFO] httpx: HTTP Request: POST https://inference.mlmp.ti.bfh.ch/api/v1/chat/completions "HTTP/1.1 200 OK"
[LLMClient] model=gpt-oss:120b in=143 out=109 latency=1689ms
2026-04-20 12:37:43,655 [INFO] httpx: HTTP Request: POST https://inference.mlmp.ti.bfh.ch/api/v1/chat/completions "HTTP/1.1 200 OK"
[LLMClient] model=gpt-oss:120b in=130 out=96 latency=1435ms
2026-04-20 12:37:43,659 [INFO] tier3_synthesis.prisma_reporter: PRISMAReporter: review report saved to data/reports/review_report.md

============================================================
  SYSTEMATIC REVIEW COMPLETE
============================================================
  Title:           AI in education systematic review
  Research Q:      Does AI improve student academic performance?
============================================================
  Records identified:            1503
  After deduplication:            915
  Screened (abstract):            135
  Full texts sought:              120
  Full texts assessed:             51
  Studies included:                51
  Studies excluded:                 0
  Uncertain:                       15
============================================================
  PRISMA flow:     data/reports/prisma_flow.md
  Review report:   data/reports/review_report.md
============================================================

2026-04-20 12:37:43,660 [INFO] __main__: Pipeline complete. Included=51, Excluded=0, Uncertain=15