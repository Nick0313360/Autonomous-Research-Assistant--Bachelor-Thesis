from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional, Dict

import numpy as np

# Reuse existing Module 2/Model types for compatibility
from slr_agent.module2_screening.models import Paper, EmbeddedPaper


@dataclass
class RankedPaper:
    paper: Paper
    embedding: np.ndarray
    simScore: float
    paperId: str

    def toDict(self) -> dict:
        return {
            **self.paper.toDict(),
            "simScore": round(self.simScore, 6),
            "paperId": self.paperId,
        }


@dataclass
class ScreeningResult:
    rankedPaper: RankedPaper
    decision: Literal["INCLUDE", "EXCLUDE", "UNCERTAIN"]
    confidence: float
    rawResponse: Optional[str] = None
    method: str = "llm_primary"

    def toDict(self) -> dict:
        d = {
            **self.rankedPaper.toDict(),
            "decision": self.decision,
            "confidence": round(self.confidence, 4),
            "method": self.method,
        }
        if self.rawResponse:
            d["rawResponse"] = self.rawResponse
        return d


@dataclass
class ResolvedResult:
    screeningResult: ScreeningResult
    finalDecision: Literal["INCLUDE", "EXCLUDE"]
    confidence: float
    reasoning: str
    cotSteps: Dict[str, str] = field(default_factory=dict)
    examplesUsed: int = 0

    def toDict(self) -> dict:
        return {
            **self.screeningResult.toDict(),
            "finalDecision": self.finalDecision,
            "confidence": round(self.confidence, 4),
            "reasoning": self.reasoning,
            "cotSteps": self.cotSteps,
            "examplesUsed": self.examplesUsed,
        }


@dataclass
class ScreeningOutput:
    includedPapers: List[Paper]
    excludedPapers: List[Paper]
    uncertainPapers: List[Paper]
    allDecisions: List[Dict]
    prismaSnapshot: dict

    def toDict(self) -> dict:
        return {
            "counts": {
                "included": len(self.includedPapers),
                "excluded": len(self.excludedPapers),
                "uncertain": len(self.uncertainPapers),
            },
            "prisma": self.prismaSnapshot,
        }


@dataclass
class ScreeningConfig:
    similarityThreshold: float = 0.10
    primaryConcurrency: int = 20
    uncertaintyConcurrency: int = 5
    batchSize: int = 32
    cacheDir: Optional[str] = None
