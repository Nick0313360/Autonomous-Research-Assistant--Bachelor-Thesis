"""Module 2 — Data Models"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Paper:
    """Module 1::Model::Paper"""

    title: str
    abstract: str
    doi: Optional[str] = None
    year: Optional[int] = None
    source: str = ""
    pdfLink: Optional[str] = None
    author: List[str] = field(default_factory=list)

    def toDict(self) -> dict:
        return {
            "title": self.title,
            "abstract": self.abstract,
            "doi": self.doi,
            "year": self.year,
            "source": self.source,
            "pdfLink": self.pdfLink,
            "author": self.author,
        }


@dataclass
class SearchQuery:
    """Module 1::Model::SearchQuery"""

    researchQuestion: str
    population: str
    intervention: str
    outcome: str
    comparison: str = ""
    domainKeywords: List[str] = field(default_factory=list)
    year_range: Optional[tuple[int, int]] = None
    maxPapersPerDb: int = 200

    def validate(self) -> bool:
        return bool(self.researchQuestion and self.population and self.intervention)

    def buildQueryString(self) -> str:
        parts = [
            self.researchQuestion,
            self.population,
            self.intervention,
            self.outcome,
        ]
        if self.comparison:
            parts.append(self.comparison)
        return " ".join(p for p in parts if p)

    def toDict(self) -> dict:
        return {
            "researchQuestion": self.researchQuestion,
            "population": self.population,
            "intervention": self.intervention,
            "comparison": self.comparison,
            "outcome": self.outcome,
            "domainKeywords": self.domainKeywords,
        }


@dataclass
class EmbeddedPaper:
    """
    Module 2::Model::EmbeddedPaper
    DATA IN:  paper, embedding (768,), modelId
    DATA OUT: downstream screening layers
    """

    paper: Paper
    embedding: np.ndarray
    modelId: str

    def toDict(self) -> dict:
        return {**self.paper.toDict(), "modelId": self.modelId}


@dataclass
class ScreeningResult:
    """Module 2::Model::ScreeningResult — returned to Module 3."""

    includedPapers: List[Paper]
    uncertainPapers: List[Paper]
    excludedPapers: List[Paper]
    prismaSnapshot: dict

    def toDict(self) -> dict:
        return {
            "counts": {
                "included": len(self.includedPapers),
                "uncertain": len(self.uncertainPapers),
                "excluded": len(self.excludedPapers),
            },
            "prisma": self.prismaSnapshot,
        }
