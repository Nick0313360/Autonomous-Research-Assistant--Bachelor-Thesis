"""
tier1_search/database_connector.py
=====================================
Dispatches a SearchQuery to all configured literature databases and merges
the results.

Current connectors
------------------
PubMedConnector         — NCBI PubMed via E-utilities (pubmed_connector.py)
SemanticScholarConnector — Semantic Scholar Academic Graph API
                          (semantic_scholar_connector.py)

Both connectors must expose an async ``search(query) -> List[CandidateRecord]``
method.  If a connector is not yet implemented (empty placeholder) it is
skipped silently; the orchestrator continues with whatever other connectors
are available.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List

from models.data_classes import CandidateRecord, SearchQuery

logger = logging.getLogger(__name__)


def _load_connectors():
    """Return a list of (name, connector_instance) that are available."""
    connectors = []

    try:
        from tier1_search.pubmed_connector import PubMedConnector
        connectors.append(("pubmed", PubMedConnector()))
    except (ImportError, AttributeError):
        logger.debug("DatabaseConnector: PubMedConnector not available")

    try:
        from tier1_search.semantic_scholar_connector import SemanticScholarConnector
        connectors.append(("semantic_scholar", SemanticScholarConnector()))
    except (ImportError, AttributeError):
        logger.debug("DatabaseConnector: SemanticScholarConnector not available")

    return connectors


class DatabaseConnector:
    """
    Fan-out connector: dispatches a query to every available database
    concurrently and returns the merged record list.

    If no connector is available (all are empty stubs), a warning is logged
    and an empty list is returned so the pipeline degrades gracefully.
    """

    def __init__(self) -> None:
        self._connectors = _load_connectors()
        if not self._connectors:
            logger.warning(
                "DatabaseConnector: no database connectors are available. "
                "PubMed and Semantic Scholar connectors are not yet implemented. "
                "Returning empty results."
            )

    async def execute(self, query: SearchQuery) -> List[CandidateRecord]:
        """
        Execute *query* against all available connectors concurrently.

        Parameters
        ----------
        query : SearchQuery

        Returns
        -------
        List[CandidateRecord]
            Merged (but not deduplicated) records from all sources.
        """
        if not self._connectors:
            return []

        async def _safe_search(name: str, connector) -> List[CandidateRecord]:
            try:
                results = await connector.search(query)
                logger.info(
                    "DatabaseConnector: %s returned %d records", name, len(results)
                )
                return results
            except Exception as exc:
                logger.error(
                    "DatabaseConnector: %s search failed: %s", name, exc
                )
                return []

        all_results = await asyncio.gather(
            *[_safe_search(name, conn) for name, conn in self._connectors]
        )

        merged: List[CandidateRecord] = []
        for batch in all_results:
            merged.extend(batch)

        logger.info(
            "DatabaseConnector: total %d records from %d connector(s)",
            len(merged),
            len(self._connectors),
        )
        return merged
