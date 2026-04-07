"""Module 2 — PrismaLog singleton"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional
from .models import Paper


@dataclass
class PrismaLog:
    """
    Shared singleton — Module 1 writes identification + dedup counts,
    Module 2 writes screening counts + paper lists.
    """

    identifiedPubMed: int = 0
    identifiedSemanticScholar: int = 0
    duplicatesRemovedByDoi: int = 0
    duplicatesRemovedByTitle: int = 0
    recordsAfterDeduplication: int = 0
    queriesUsed: List[str] = field(default_factory=list)
    iterationsRun: int = 0
    termsAddedPerIteration: List[List[str]] = field(default_factory=list)
    recordsScreened: int = 0
    excludedTitleAbstract: int = 0
    uncertainTitleAbstract: int = 0
    excludedTitleAbstractReasons: Dict[str, int] = field(default_factory=dict)
    papersAfterDedup: List[Paper] = field(default_factory=list)
    papersIncludedTitleAbstract: List[Paper] = field(default_factory=list)
    papersUncertain: List[Paper] = field(default_factory=list)
    papersExcludedTitleAbstract: List[Paper] = field(default_factory=list)
    embeddingModelUsed: str = ""
    separabilityScore: float = 0.0
    screeningRoute: str = ""
    stoppingCriterionTriggered: bool = False
    fullTextAssessed: int = 0
    excludedFullText: int = 0
    excludedFullTextReasons: Dict[str, int] = field(default_factory=dict)
    fullTextNotAvailable: int = 0
    studiesIncluded: int = 0
    runId: str = ""
    generatedAt: datetime = field(default_factory=datetime.now)

    _instance: Optional[PrismaLog] = field(
        default=None, init=False, repr=False, compare=False
    )

    @classmethod
    def getInstance(cls) -> PrismaLog:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def resetInstance(cls) -> None:
        cls._instance = None

    def toDict(self) -> dict:
        return {
            "identification": {
                "pubmed": self.identifiedPubMed,
                "semanticScholar": self.identifiedSemanticScholar,
                "total": self.identifiedPubMed + self.identifiedSemanticScholar,
            },
            "deduplication": {
                "removedByDoi": self.duplicatesRemovedByDoi,
                "removedByTitle": self.duplicatesRemovedByTitle,
                "totalRemoved": self.duplicatesRemovedByDoi
                + self.duplicatesRemovedByTitle,
                "recordsAfter": self.recordsAfterDeduplication,
            },
            "queryAudit": {
                "iterationsRun": self.iterationsRun,
                "queriesUsed": self.queriesUsed,
                "termsAddedPerIteration": self.termsAddedPerIteration,
            },
            "screening": {
                "recordsScreened": self.recordsScreened,
                "excludedTitleAbstract": self.excludedTitleAbstract,
                "uncertain": self.uncertainTitleAbstract,
                "excludedReasons": self.excludedTitleAbstractReasons,
                "route": self.screeningRoute,
                "dbs": self.separabilityScore,
                "embeddingModel": self.embeddingModelUsed,
                "stopTriggered": self.stoppingCriterionTriggered,
                "paperListsIncluded": len(self.papersIncludedTitleAbstract),
                "paperListsUncertain": len(self.papersUncertain),
                "paperListsExcluded": len(self.papersExcludedTitleAbstract),
            },
            "eligibility": {
                "fullTextAssessed": self.fullTextAssessed,
                "excludedFullText": self.excludedFullText,
                "excludedReasons": self.excludedFullTextReasons,
                "notAvailable": self.fullTextNotAvailable,
            },
            "inclusion": {"studiesIncluded": self.studiesIncluded},
            "meta": {"runId": self.runId, "generatedAt": self.generatedAt.isoformat()},
        }
