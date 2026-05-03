import logging
from rapidfuzz import fuzz
from typing import List, Tuple
from dataclasses import dataclass
from module1.model.Paper import Paper

logger = logging.getLogger(__name__)


@dataclass
class DeduplicationStats:
    """Counts for PRISMA logging — who removed what and why."""
    inputCount: int = 0
    outputCount: int = 0
    doiDuplicates: int = 0
    titleDuplicates: int = 0
    totalRemoved: int = 0


class DeduplicationService:

    def __init__(self, threshold: float = 0.9):
        self.__threshold: float = float(threshold)

    def deduplicate(self, papers: List[Paper]) -> Tuple[List[Paper], DeduplicationStats]:
        # Two phase deduplication.
        # Phase 1 — exact DOI match on normalised DOI string.
        # Phase 2 — fuzzy title match at threshold on remaining papers.
        # Returns clean list and stats for PRISMA logging.

        stats = DeduplicationStats(inputCount=len(papers))

        afterDoi, doiRemoved = self.deduplicateByDoi(papers)
        stats.doiDuplicates = doiRemoved

        afterTitle, titleRemoved = self.deduplicateByTitle(afterDoi)
        stats.titleDuplicates = titleRemoved

        stats.outputCount = len(afterTitle)
        stats.totalRemoved = doiRemoved + titleRemoved

        logger.info(
            "Deduplication: %d in → %d unique (doi removed: %d, title removed: %d)",
            stats.inputCount, stats.outputCount, stats.doiDuplicates, stats.titleDuplicates
        )

        return afterTitle, stats

    def deduplicateByDoi(self, papers: List[Paper]) -> Tuple[List[Paper], int]:
        seen: dict = {}
        removed = 0

        for paper in papers:
            if not paper.doi:
                continue
            normalised = self.__normaliseDoi(paper.doi)
            if normalised in seen:
                # prefer the one with an abstract
                if paper.abstract and not seen[normalised].abstract:
                    seen[normalised] = paper
                removed += 1
            else:
                seen[normalised] = paper

        # add papers with no DOI — they skip DOI dedup entirely
        noDoi = [p for p in papers if not p.doi]
        unique = list(seen.values()) + noDoi

        return unique, removed

    def deduplicateByTitle(self, papers: List[Paper]) -> Tuple[List[Paper], int]:
        if not papers:
            return [], 0

        unique: List[Paper] = []
        removed = 0

        for paper in papers:
            isDuplicate = False
            for kept in unique:
                similarity = fuzz.ratio(
                    paper.title.lower(),
                    kept.title.lower()
                ) / 100.0
                if similarity >= self.__threshold:
                    isDuplicate = True
                    removed += 1
                    break
            if not isDuplicate:
                unique.append(paper)

        return unique, removed

    def findDuplicates(self, papers: List[Paper]) -> List[Tuple[Paper, Paper]]:
        duplicates: List[Tuple[Paper, Paper]] = []
        alreadyDuped = set()

        # DOI duplicates
        seenDois: dict = {}
        for paper in papers:
            if paper.doi:
                normalised = self.__normaliseDoi(paper.doi)
                if normalised in seenDois:
                    duplicates.append((seenDois[normalised], paper))
                    alreadyDuped.add(id(paper))
                    alreadyDuped.add(id(seenDois[normalised]))
                else:
                    seenDois[normalised] = paper

        # title duplicates — only on papers not already caught by DOI
        remaining = [p for p in papers if id(p) not in alreadyDuped]
        for i, paper1 in enumerate(remaining):
            for j, paper2 in enumerate(remaining):
                if i >= j:
                    continue
                similarity = fuzz.ratio(
                    paper1.title.lower(),
                    paper2.title.lower()
                ) / 100.0
                if similarity >= self.__threshold:
                    duplicates.append((paper1, paper2))

        return duplicates

    def __normaliseDoi(self, doi: str) -> str:
        """Strip common DOI prefixes for consistent comparison."""
        doi = doi.lower().strip()
        for prefix in ["https://doi.org/", "http://doi.org/", "doi:"]:
            if doi.startswith(prefix):
                doi = doi[len(prefix):]
        return doi