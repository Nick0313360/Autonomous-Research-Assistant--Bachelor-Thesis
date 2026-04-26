"""
orchestrators/search_orchestrator.py
=======================================
Drives the iterative literature search pipeline.

Pipeline (per iteration, up to 3)
----------------------------------
1. QueryBuilder.build_initial_queries(protocol)         → List[SearchQuery]
2. DatabaseConnector.execute(query) for each query      → List[CandidateRecord]
3. Merge all per-query result lists
4. DeduplicationEngine.deduplicate(merged)              → unique records
5. CoverageAnalyzer.analyze(unique, protocol, queries)  → CoverageReport
6. If report.has_gaps and iteration < _MAX_ITER:
     SearchRefinementAgent.refine(queries, report, ...)  → updated queries
     Loop back to step 2 with updated queries
7. PRISMAManager.record_identification / record_deduplication
8. Return deduplicated candidates
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, List

from models.data_classes import CandidateRecord, ReviewProtocol
from tier1_search.coverage_analyzer import CoverageAnalyzer
from tier1_search.database_connector import DatabaseConnector
from tier1_search.deduplication import DeduplicationEngine
from tier1_search.query_builder import QueryBuilder
from tier1_search.search_refinement import SearchRefinementAgent
from infrastructure.prisma_manager import PRISMAManager

logger = logging.getLogger(__name__)

_MAX_ITER = 3


class SearchOrchestrator:
    """
    Manages the iterative search-refine loop for a single review.

    Parameters
    ----------
    llm_client : LLMClient
        Required by SearchRefinementAgent for query expansion.
    review_id : str
        Passed to PRISMAManager for audit logging.
    """

    def __init__(self, llm_client: Any, review_id: str) -> None:
        self._llm_client          = llm_client
        self._query_builder       = QueryBuilder()
        self._db_connector        = DatabaseConnector()
        self._dedup_engine        = DeduplicationEngine()
        self._coverage_analyzer   = CoverageAnalyzer()
        self._refinement_agent    = SearchRefinementAgent()
        self._prisma              = PRISMAManager(review_id)

    async def run(self, protocol: ReviewProtocol) -> List[CandidateRecord]:
        """
        Execute the full search pipeline and return deduplicated candidates.

        Parameters
        ----------
        protocol : ReviewProtocol

        Returns
        -------
        List[CandidateRecord]
            Deduplicated records ready for abstract screening.
        """
        queries          = self._query_builder.build_initial_queries(protocol)
        previous_count   = 0
        all_records: List[CandidateRecord] = []
        total_identified = 0   # cumulative raw records before deduplication

        for iteration in range(_MAX_ITER):
            logger.info(
                "SearchOrchestrator: iteration %d/%d — %d queries",
                iteration + 1, _MAX_ITER, len(queries),
            )

            # Track query version strings
            for q in queries:
                self._prisma.add_query_version(
                    f"iter{iteration+1}: {q.research_question[:60]}"
                )

            # Step 2: execute all queries concurrently
            batch_results = await asyncio.gather(
                *[self._db_connector.execute(q) for q in queries]
            )
            raw: List[CandidateRecord] = []
            for batch in batch_results:
                raw.extend(batch)

            total_identified += len(raw)
            logger.info(
                "SearchOrchestrator: iteration %d — %d raw records retrieved",
                iteration + 1, len(raw),
            )

            # Step 3 & 4: merge with previous iterations and deduplicate
            combined = all_records + raw
            deduped   = self._dedup_engine.deduplicate(combined)
            n_removed = len(self._dedup_engine.duplicate_pairs)

            logger.info(
                "SearchOrchestrator: iteration %d — %d unique records (%d duplicates removed)",
                iteration + 1, len(deduped), n_removed,
            )

            # Step 5: coverage analysis
            report = self._coverage_analyzer.analyze(
                records        = deduped,
                protocol       = protocol,
                previous_count = previous_count,
                queries        = queries,
            )

            all_records    = deduped
            previous_count = len(deduped)

            # Step 6: refine or stop
            if not report.has_gaps or iteration >= _MAX_ITER - 1:
                if not report.has_gaps:
                    logger.info(
                        "SearchOrchestrator: no coverage gaps — stopping at iteration %d",
                        iteration + 1,
                    )
                break

            logger.info(
                "SearchOrchestrator: %d gaps found, refining queries",
                len(report.identified_gaps),
            )
            queries = await self._refinement_agent.refine(
                queries         = queries,
                coverage_report = report,
                protocol        = protocol,
                llm_client      = self._llm_client,
                iteration       = iteration,
            )

        # Step 7: PRISMA accounting
        # total_identified = sum of all raw records fetched across iterations (pre-dedup)
        # all_records      = final deduplicated list
        # duplicates_removed = raw total − unique total
        duplicates_removed = total_identified - len(all_records)
        self._prisma.record_identification(total_identified)
        self._prisma.record_deduplication(duplicates_removed)

        logger.info(
            "SearchOrchestrator: returning %d candidates after %d iteration(s) "
            "(%d raw identified, %d duplicates removed)",
            len(all_records),
            min(_MAX_ITER, iteration + 1),
            total_identified,
            duplicates_removed,
        )
        return all_records

    @property
    def prisma(self) -> PRISMAManager:
        return self._prisma
