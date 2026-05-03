"""
tier1_search/query_builder.py
================================
Builds initial SearchQuery objects from a ReviewProtocol.

Derives domain_keywords from PICO field tokens.  One query is produced per
protocol; the SearchRefinementAgent will expand it over subsequent iterations.
"""
from __future__ import annotations

import re
from typing import List

from models.data_classes import ReviewProtocol, SearchQuery

_MIN_WORD_LEN = 3


class QueryBuilder:
    """
    Converts a ReviewProtocol into a list of SearchQuery objects ready for
    database dispatch.
    """

    def build_initial_queries(self, protocol: ReviewProtocol) -> List[SearchQuery]:
        """
        Parameters
        ----------
        protocol : ReviewProtocol

        Returns
        -------
        List[SearchQuery]
            A single SearchQuery whose domain_keywords are derived from the
            PICO fields and (if set) the protocol's date_range.
        """
        pico = protocol.pico
        raw_terms: List[str] = []
        for field_val in (
            pico.population,
            pico.intervention,
            pico.comparator,
            pico.outcome,
        ):
            for token in re.split(r"[\s,;/()\[\]]+", field_val):
                token = token.strip().lower()
                if len(token) >= _MIN_WORD_LEN:
                    raw_terms.append(token)

        # Deduplicate while preserving order
        seen: set = set()
        keywords: List[str] = []
        for t in raw_terms:
            if t not in seen:
                seen.add(t)
                keywords.append(t)

        year_range = None
        if protocol.date_range:
            year_range = protocol.date_range

        query = SearchQuery(
            research_question = protocol.research_question,
            population        = pico.population,
            intervention      = pico.intervention,
            outcome           = pico.outcome,
            comparison        = pico.comparator,
            domain_keywords   = keywords,
            year_range        = year_range,
            max_papers_per_db = protocol.max_papers_per_db,
        )
        return [query]
