from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional


@dataclass
class PrismaLog:
    # ── Module 1 — Identification ──────────────────────────
    identifiedPubMed: int = 0
    identifiedSemanticScholar: int = 0

    # ── Module 1 — Deduplication ───────────────────────────
    duplicatesRemovedByDoi: int = 0
    duplicatesRemovedByTitle: int = 0
    recordsAfterDeduplication: int = 0

    # ── Module 1 — Query audit trail ──────────────────────
    queriesUsed: List[str] = field(default_factory=list)
    iterationsRun: int = 0
    termsAddedPerIteration: List[List[str]] = field(default_factory=list)

    # ── Module 2 — Screening ───────────────────────────────
    recordsScreened: int = 0
    excludedTitleAbstract: int = 0
    excludedTitleAbstractReasons: Dict[str, int] = field(default_factory=dict)

    # ── Module 2 — Eligibility ─────────────────────────────
    fullTextAssessed: int = 0
    excludedFullText: int = 0
    excludedFullTextReasons: Dict[str, int] = field(default_factory=dict)
    fullTextNotAvailable: int = 0

    # ── Module 3 + 4 — Inclusion ───────────────────────────
    studiesIncluded: int = 0

    # ── Metadata ───────────────────────────────────────────
    runId: str = ""
    generatedAt: datetime = field(default_factory=datetime.now)

    # ── Singleton — class variable, NOT a dataclass field ──
    # stored at class level so dataclass __init__ never touches it
    _instance: Optional[PrismaLog] = None

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
                "totalRemoved": self.duplicatesRemovedByDoi + self.duplicatesRemovedByTitle,
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
                "excludedReasons": self.excludedTitleAbstractReasons,
            },
            "eligibility": {
                "fullTextAssessed": self.fullTextAssessed,
                "excludedFullText": self.excludedFullText,
                "excludedReasons": self.excludedFullTextReasons,
                "notAvailable": self.fullTextNotAvailable,
            },
            "inclusion": {
                "studiesIncluded": self.studiesIncluded,
            },
            "meta": {
                "runId": self.runId,
                "generatedAt": self.generatedAt.isoformat(),
            }
        }