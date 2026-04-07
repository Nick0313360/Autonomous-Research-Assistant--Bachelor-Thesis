import os
import logging

from module1.model.SearchQuery import SearchQuery
from module1.data.PrismaLog import PrismaLog
from module1.connector.PubMedConnector import PubMedConnector
from module1.connector.SemanticScholarConnector import SemanticScholarConnector
from module1.connector.GptConnector import GptConnector
from module1.services.DeduplicationService import DeduplicationService
from module1.services.DomainValidator import DomainValidator
from module1.services.PaperSampler import PaperSampler
from module1.services.LLMRefinerService import LLMRefinerService
from orchestrator.SearchService import SearchService

from dotenv import load_dotenv
load_dotenv()  # automatically loads .env in project root

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def buildSearchQuery() -> SearchQuery:
    """
    Research query: AI agents for systematic literature review automation.
    Change these fields to test any other research topic.
    """
    return SearchQuery(
        researchQuestion=(
            "How do large language models and AI agents automate "
            "the systematic literature review process?"
        ),
        population="systematic reviews, literature reviews, evidence synthesis",
        intervention="LLM, large language model, GPT, AI agent, artificial intelligence",
        outcome="screening automation, title screening, abstract screening, PRISMA",
        comparison=None,
        domainKeywords=[
            "systematic review", "LLM", "screening", "PRISMA",
            "evidence synthesis", "automation", "AI agent",
            "machine learning", "natural language processing",
            "text mining", "prompt engineering", "semantic search",
            "artificial intelligence"
        ],
        maxPapersPerDb=1000,
    )


def buildSearchService() -> SearchService:
    """
    Wires up all dependencies and returns a ready SearchService.
    Reads all credentials from .env — never hardcoded here.
    """
    # connectors
    pubmed = PubMedConnector(
        apiKey=os.getenv("PUBMED_API_KEY", ""),
        email=os.getenv("PUBMED_EMAIL", ""),
    )
    semantic = SemanticScholarConnector(
        apiKey=os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""),
    )
    llm = GptConnector(
        baseUrl=os.getenv("OPENAI_BASE_URL", "https://inference.mlmp.ti.bfh.ch/api/v1"),
        apiKey=os.getenv("OPENAI_API_KEY", ""),
        modelName=os.getenv("OPENAI_MODEL", "gpt-oss:120b"),
    )

    # services
    deduplicator = DeduplicationService(threshold=0.9)
    validator = DomainValidator(vocabulary=frozenset())
    sampler = PaperSampler()
    refiner = LLMRefinerService(llm=llm, validator=validator, sampler=sampler)

    return SearchService(
        connectors=[pubmed, semantic],
        deduplicator=deduplicator,
        refiner=refiner,
    )


def printResults(searchRun, prisma: PrismaLog) -> None:
    """Prints a clean summary of what the search found."""

    print("\n" + "=" * 60)
    print("SEARCH COMPLETE")
    print("=" * 60)

    print(f"\nRun ID   : {searchRun.runId}")
    print(f"Mode     : {searchRun.mode}")
    print(f"Created  : {searchRun.createdAt}")

    print("\n── PRISMA Identification ──────────────────────────────")
    print(f"PubMed identified        : {prisma.identifiedPubMed}")
    print(f"Semantic Scholar         : {prisma.identifiedSemanticScholar}")
    print(f"Total raw                : {prisma.identifiedPubMed + prisma.identifiedSemanticScholar}")

    print("\n── PRISMA Deduplication ───────────────────────────────")
    print(f"Removed by DOI           : {prisma.duplicatesRemovedByDoi}")
    print(f"Removed by title         : {prisma.duplicatesRemovedByTitle}")
    print(f"Total removed            : {prisma.duplicatesRemovedByDoi + prisma.duplicatesRemovedByTitle}")
    print(f"Records after dedup      : {prisma.recordsAfterDeduplication}")

    print("\n── Query Audit ────────────────────────────────────────")
    print(f"Iterations run           : {prisma.iterationsRun}")
    for i, query in enumerate(prisma.queriesUsed, 1):
        print(f"  Iteration {i} query: {query[:80]}...")
    for i, terms in enumerate(prisma.termsAddedPerIteration, 1):
        print(f"  Iteration {i} new terms: {terms}")

    print("\n── Final Papers ───────────────────────────────────────")
    print(f"Total unique papers      : {len(searchRun.finalPapers)}")
    print()

    for i, paper in enumerate(searchRun.finalPapers[:20], 1):
        print(f"[{i:02d}] {paper.title}")
        print(f"      Year   : {paper.year}  |  Source : {paper.source}  |  DOI : {paper.doi}")
        if paper.abstract:
            print(f"      Abstract: {paper.abstract[:120]}...")
        print()

    if len(searchRun.finalPapers) > 20:
        print(f"... and {len(searchRun.finalPapers) - 20} more papers not shown")

    print("=" * 60)


def main():
    # reset prisma log at the start of every run
    PrismaLog.resetInstance()

    searchQuery = buildSearchQuery()
    searchService = buildSearchService()

    print("\nStarting Module 1 — Search and Iterative Refinement")
    print(f"Research question: {searchQuery.researchQuestion}")
    
    mode_v = "basic"
    searchRun = searchService.runSearch(searchQuery=searchQuery, mode= mode_v)
    print(f"Mode: {mode_v}")
    print("-" * 60)
    prisma = PrismaLog.getInstance()
    prisma.runId = searchRun.runId

    printResults(searchRun, prisma)


if __name__ == "__main__":
    main()