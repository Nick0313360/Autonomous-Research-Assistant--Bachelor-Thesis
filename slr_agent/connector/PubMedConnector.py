import time
import logging
from typing import List, Optional

from Bio import Entrez, Medline

from connector.BaseConnector import BaseConnector
from model.Paper import Paper

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