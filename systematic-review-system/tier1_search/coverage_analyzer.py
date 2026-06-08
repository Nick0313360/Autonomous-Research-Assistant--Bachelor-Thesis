"""
tier1_search/coverage_analyzer.py
==================================
Analyses a corpus of CandidateRecords against a ReviewProtocol to detect
retrieval gaps before committing to screening.

Three checks
------------
temporal_coverage
    Are there years with an unusually low paper count (< mean − 2·std)?
    Only evaluated when ≥ 3 distinct years are present.

keyword_coverage
    Does each PICO term appear in at least 5 % of record titles/abstracts?
    Terms are derived from the protocol's PICO fields and domain_keywords of
    the provided queries.

saturation
    If this is not the first iteration, are fewer than 5 % of the records
    genuinely new (not seen in previous iterations)?
    Pass previous_count=0 for the first iteration to skip this check.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from models.data_classes import CandidateRecord, ReviewProtocol

logger = logging.getLogger(__name__)

_KEYWORD_MIN_FRACTION = 0.05   # 5 % of abstracts must contain a PICO term
_SATURATION_THRESHOLD  = 0.05  # < 5 % new records → saturated


# ---------------------------------------------------------------------------
# CoverageReport dataclass
# ---------------------------------------------------------------------------

@dataclass
class CoverageReport:
    """Output of CoverageAnalyzer.analyze()."""

    temporal_coverage: Dict[str, Any]
    """
    {
      "year_counts": {2018: 12, 2019: 30, ...},
      "flagged_years": [2018],          # years below mean−2·std
      "mean": 25.0,
      "std": 6.5,
      "check_performed": True
    }
    """

    keyword_coverage: Dict[str, Any]
    """
    {
      "term": {"count": 42, "fraction": 0.084, "covered": True},
      ...
    }
    """

    saturation: Dict[str, Any]
    """
    {
      "new_fraction": 0.12,
      "new_count": 60,
      "total_count": 500,
      "is_saturated": False,
      "check_performed": True
    }
    """

    has_gaps: bool
    identified_gaps: List[str] = field(default_factory=list)
    total_records: int = 0


# ---------------------------------------------------------------------------
# CoverageAnalyzer
# ---------------------------------------------------------------------------

class CoverageAnalyzer:
    """
    Stateless analyzer.  Call ``analyze()`` with the current corpus.
    """

    def analyze(
        self,
        records: List[CandidateRecord],
        protocol: ReviewProtocol,
        previous_count: int = 0,
        queries: Optional[List[Any]] = None,   # List[SearchQuery], optional
    ) -> CoverageReport:
        """
        Parameters
        ----------
        records :
            Current deduplicated corpus.
        protocol :
            Review protocol supplying PICO terms and date_range.
        previous_count :
            Number of records from all previous iterations combined.
            0 → skip saturation check.
        queries :
            Optional list of SearchQuery objects; their domain_keywords are
            added to the PICO terms checked for keyword coverage.
        """
        temporal  = self._check_temporal(records, protocol)
        keywords  = self._check_keywords(records, protocol, queries or [])
        saturation = self._check_saturation(records, previous_count)

        gaps: List[str] = []

        if temporal["check_performed"] and temporal["flagged_years"]:
            years = temporal["flagged_years"]
            gaps.append(
                f"Temporal gap: low record counts in years {years} "
                f"(mean={temporal['mean']:.1f}, std={temporal['std']:.1f})"
            )

        for term, info in keywords.items():
            if not info["covered"]:
                gaps.append(
                    f"Keyword gap: term '{term}' appears in only "
                    f"{info['fraction']:.1%} of records "
                    f"(threshold {_KEYWORD_MIN_FRACTION:.0%})"
                )

        if saturation["check_performed"] and saturation["is_saturated"]:
            gaps.append(
                f"Saturation: only {saturation['new_fraction']:.1%} new records "
                f"({saturation['new_count']}/{saturation['total_count']})"
            )

        logger.info(
            "Coverage analysis: %d records, %d gaps found",
            len(records),
            len(gaps),
        )

        return CoverageReport(
            temporal_coverage=temporal,
            keyword_coverage=keywords,
            saturation=saturation,
            has_gaps=bool(gaps),
            identified_gaps=gaps,
            total_records=len(records),
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    @staticmethod
    def _check_temporal(
        records: List[CandidateRecord],
        protocol: ReviewProtocol,
    ) -> Dict[str, Any]:
        years = [r.year for r in records if r.year is not None]
        if len(set(years)) < 3:
            return {
                "year_counts": {},
                "flagged_years": [],
                "mean": 0.0,
                "std": 0.0,
                "check_performed": False,
            }

        year_counts: Dict[int, int] = {}
        for y in years:
            year_counts[y] = year_counts.get(y, 0) + 1

        # Filter to protocol date_range if set
        if protocol.date_range:
            start, end = protocol.date_range
            year_counts = {y: c for y, c in year_counts.items() if start <= y <= end}

        counts = np.array(list(year_counts.values()), dtype=float)
        mean = float(counts.mean())
        std  = float(counts.std())
        threshold = mean - 2 * std

        flagged = [y for y, c in year_counts.items() if c < threshold]

        return {
            "year_counts": year_counts,
            "flagged_years": sorted(flagged),
            "mean": mean,
            "std": std,
            "check_performed": True,
        }

    @staticmethod
    def _check_keywords(
        records: List[CandidateRecord],
        protocol: ReviewProtocol,
        queries: List[Any],
    ) -> Dict[str, Any]:
        pico = protocol.pico
        terms: List[str] = []
        for val in (pico.population, pico.intervention, pico.comparator, pico.outcome):
            # Split multi-word PICO values into individual terms
            for word in re.split(r"[\s,;/]+", val):
                w = word.strip().lower()
                if len(w) >= 3:
                    terms.append(w)

        for q in queries:
            for kw in getattr(q, "domain_keywords", []):
                k = kw.strip().lower()
                if k and k not in terms:
                    terms.append(k)

        # Build searchable text per record
        corpora: List[str] = []
        for r in records:
            parts = [r.title]
            if r.abstract:
                parts.append(r.abstract)
            corpora.append(" ".join(parts).lower())

        total = len(corpora) or 1
        result: Dict[str, Any] = {}
        seen_terms: set[str] = set()

        for term in terms:
            if term in seen_terms:
                continue
            seen_terms.add(term)
            count = sum(1 for text in corpora if term in text)
            fraction = count / total
            result[term] = {
                "count":    count,
                "fraction": fraction,
                "covered":  fraction >= _KEYWORD_MIN_FRACTION,
            }

        return result

    @staticmethod
    def _check_saturation(
        records: List[CandidateRecord],
        previous_count: int,
    ) -> Dict[str, Any]:
        if previous_count <= 0:
            return {
                "new_fraction": 1.0,
                "new_count": len(records),
                "total_count": len(records),
                "is_saturated": False,
                "check_performed": False,
            }

        total = len(records)
        new_count = max(0, total - previous_count)
        new_fraction = new_count / total if total else 0.0
        is_saturated = new_fraction < _SATURATION_THRESHOLD

        return {
            "new_fraction": new_fraction,
            "new_count":    new_count,
            "total_count":  total,
            "is_saturated": is_saturated,
            "check_performed": True,
        }
