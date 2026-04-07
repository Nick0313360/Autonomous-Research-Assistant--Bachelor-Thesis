"""Module 2 — Orchestrator (ScreeningOrchestrator)"""

from __future__ import annotations

from typing import List, Optional

from .models import (
    Paper,
    SearchQuery,
    EmbeddedPaper,
    ScreeningResult,
)
from .connectors import GptConnector
from .prisma_log import PrismaLog
from .layers import (
    EmbeddingLayer,
    _log,
)


class ScreeningOrchestrator:
    """
    Module 2::Orchestrator::ScreeningOrchestrator

    No ML logic here — sequencing and accumulation only.

    DATA FLOW:
      papers + query
        → L1 → embedded (List[EmbeddedPaper]) + picoEmb (768,)
        → ScreeningResult
    """

    def __init__(
        self,
        llmConnector: Optional[GptConnector] = None,
        reevalConnector: Optional[GptConnector] = None,
        windowSize: int = 50,
        maxEmptyWindows: int = 3,
        includeThresh: float = 0.70,
        excludeThresh: float = 0.30,
    ):
        self._l1 = EmbeddingLayer()

    def runScreening(
        self,
        papers: List[Paper],
        query: SearchQuery,
        emitLog: Optional[callable] = None,
    ) -> ScreeningResult:
        prisma = PrismaLog.getInstance()
        prisma.recordsScreened = len(papers)
        prisma.papersAfterDedup = list(papers)
        _log(emitLog, f"Starting screening of {len(papers)} papers", count=len(papers))

        modelKey = self._l1.selectModel(query)
        embedded = self._l1.embedPapers(papers, modelKey, batchSize=32)
        picoEmb = self._l1.embedQuery(query, modelKey)
        prisma.embeddingModelUsed = modelKey
        _log(emitLog, f"L1: embedded {len(embedded)} papers with {modelKey}")

        _log(
            emitLog,
            f"Screening complete: included=0 uncertain=0 excluded=0",
            count=0,
        )

        return ScreeningResult(
            includedPapers=[],
            uncertainPapers=[],
            excludedPapers=[],
            prismaSnapshot=prisma.toDict(),
        )


def runPipeline(formData: dict, emitLog: callable) -> dict:
    """Module 1 → Module 2 hand-off called by your /run endpoint."""
    query = SearchQuery(
        researchQuestion=formData.get("research_question", ""),
        population=formData.get("population", ""),
        intervention=formData.get("intervention", ""),
        outcome=formData.get("outcome", ""),
        comparison=formData.get("comparison", ""),
        domainKeywords=[
            k.strip()
            for k in formData.get("domain_keywords", "").split(",")
            if k.strip()
        ],
        maxPapersPerDb=int(formData.get("max_papers_per_db", 200)),
    )
    orchestrator = ScreeningOrchestrator()
    result = orchestrator.runScreening([], query, emitLog)
    return result.toDict()
