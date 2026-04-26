"""
orchestrators/main_orchestrator.py
=====================================
Top-level entry point for a complete autonomous systematic review run.

Sequence
--------
1. SearchOrchestrator.run(protocol)         → deduplicated candidates
2. ScreeningOrchestrator.run(candidates)    → ScreeningOutput
3. DataExtractor.extract_batch(included)    → extracted data tables
4. QualityAssessor.assess_batch(included)   → quality / RoB assessments
5. PRISMAReporter.generate_flow_diagram()   → prisma_flow.txt
6. PRISMAReporter.generate_review_report()  → review_report.json
7. Print console summary

Usage
-----
    import asyncio
    from orchestrators.main_orchestrator import MainOrchestrator
    from infrastructure.llm_client import LLMClient
    from infrastructure.encoder import SharedEncoderService

    encoder    = SharedEncoderService()
    llm_client = LLMClient()
    orch       = MainOrchestrator(encoder, llm_client, review_id="my_review")
    asyncio.run(orch.run(protocol))
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from models.data_classes import ReviewProtocol
from orchestrators.search_orchestrator import SearchOrchestrator
from orchestrators.screening_orchestrator import ScreeningOrchestrator, ScreeningOutput
from infrastructure.prisma_manager import PRISMAManager
from tier3_synthesis.data_extractor import DataExtractionAgent
from tier3_synthesis.quality_assessor import QualityAssessor
from tier3_synthesis.prisma_reporter import PRISMAReporter

logger = logging.getLogger(__name__)


class MainOrchestrator:
    """
    Full systematic review pipeline orchestrator.

    Parameters
    ----------
    encoder :    SharedEncoderService
    llm_client : LLMClient
    review_id :  str  — identifies this review run; used for file storage
                        and audit logging.
    output_dir : str  — base directory for PRISMA reports.
    """

    def __init__(
        self,
        encoder:    Any,
        llm_client: Any,
        review_id:  str,
        output_dir: str = "data/reports",
    ) -> None:
        self._encoder    = encoder
        self._llm_client = llm_client
        self._review_id  = review_id

        # Shared PRISMAManager so both orchestrators write to the same state
        self._prisma = PRISMAManager(review_id)

        self._search_orch = SearchOrchestrator(
            llm_client = llm_client,
            review_id  = review_id,
        )
        self._screening_orch = ScreeningOrchestrator(
            encoder    = encoder,
            llm_client = llm_client,
            review_id  = review_id,
            prisma     = self._prisma,
        )
        self._data_extractor   = DataExtractionAgent()
        self._quality_assessor = QualityAssessor()
        self._reporter         = PRISMAReporter(output_dir=output_dir)

    async def run(self, protocol: ReviewProtocol) -> ScreeningOutput:
        """
        Execute the complete review pipeline.

        Parameters
        ----------
        protocol : ReviewProtocol

        Returns
        -------
        ScreeningOutput
            Contains included / excluded / uncertain FinalDecision lists and
            the included StructuredDocuments.
        """
        logger.info(
            "MainOrchestrator: starting review '%s' (id=%s)",
            protocol.title, self._review_id,
        )

        # ------------------------------------------------------------------
        # Phase 1: Search
        # ------------------------------------------------------------------
        logger.info("MainOrchestrator: Phase 1 — Literature search")
        candidates = await self._search_orch.run(protocol)

        if not candidates:
            logger.warning(
                "MainOrchestrator: search returned 0 candidates. "
                "Check database connectors and query configuration."
            )

        # Carry over PRISMA counts from search orchestrator's internal manager
        # (search orch creates its own PRISMAManager; merge its counts)
        self._merge_prisma(self._search_orch.prisma)

        logger.info(
            "MainOrchestrator: Phase 1 complete — %d candidates", len(candidates)
        )

        # ------------------------------------------------------------------
        # Phase 2: Screening
        # ------------------------------------------------------------------
        logger.info("MainOrchestrator: Phase 2 — Screening (%d candidates)", len(candidates))
        screening_output: ScreeningOutput = await self._screening_orch.run(
            candidates, protocol
        )
        logger.info(
            "MainOrchestrator: Phase 2 complete — "
            "include=%d exclude=%d uncertain=%d",
            len(screening_output.included),
            len(screening_output.excluded),
            len(screening_output.uncertain),
        )

        # ------------------------------------------------------------------
        # Phase 3: Data extraction (stub)
        # ------------------------------------------------------------------
        included_docs = screening_output.included_docs
        if included_docs:
            logger.info(
                "MainOrchestrator: Phase 3 — Data extraction (%d documents)",
                len(included_docs),
            )
            extracted_data = await self._data_extractor.extract_batch(
                documents  = included_docs,
                protocol   = protocol,
                llm_client = self._llm_client,
            )
        else:
            extracted_data = []

        # ------------------------------------------------------------------
        # Phase 4: Quality assessment (stub)
        # ------------------------------------------------------------------
        if included_docs:
            logger.info("MainOrchestrator: Phase 4 — Quality assessment")
            quality_data = await self._quality_assessor.assess_batch(
                documents      = included_docs,
                extracted_data = extracted_data,
                protocol       = protocol,
                llm_client     = self._llm_client,
            )
        else:
            quality_data = []

        # ------------------------------------------------------------------
        # Phase 5 & 6: PRISMA reporting
        # ------------------------------------------------------------------
        prisma_counts = self._prisma.generate_prisma_counts()

        flow_path   = self._reporter.generate_flow_diagram(prisma_counts)
        included_ids = [fd.decision_record_id for fd in screening_output.included]
        report_path = await self._reporter.generate_review_report(
            protocol            = protocol,
            included_studies    = included_ids,
            extracted_data      = extracted_data,
            quality_assessments = quality_data,
            prisma_state        = prisma_counts,
            llm_client          = self._llm_client,
        )

        # ------------------------------------------------------------------
        # Phase 7: Console summary
        # ------------------------------------------------------------------
        self._print_summary(protocol, candidates, screening_output, prisma_counts,
                            flow_path, report_path)

        return screening_output

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _merge_prisma(self, source: PRISMAManager) -> None:
        """Copy identification counts from source into self._prisma."""
        source_counts = source.generate_prisma_counts()
        n_identified  = source_counts.get("records_identified", 0)
        n_dupes       = source_counts.get("duplicates_removed", 0)
        if n_identified:
            self._prisma.record_identification(n_identified)
        self._prisma.record_deduplication(n_dupes)

    @staticmethod
    def _print_summary(
        protocol:          ReviewProtocol,
        candidates:        list,
        output:            ScreeningOutput,
        prisma_counts:     dict,
        flow_path:         str,
        report_path:       str,
    ) -> None:
        sep = "=" * 60
        print(f"\n{sep}")
        print(f"  SYSTEMATIC REVIEW COMPLETE")
        print(sep)
        print(f"  Title:           {protocol.title}")
        print(f"  Research Q:      {protocol.research_question[:70]}")
        print(sep)
        print(f"  Records identified:          {prisma_counts.get('records_identified', 0):>6}")
        print(f"  After deduplication:         {prisma_counts.get('records_after_deduplication', 0):>6}")
        print(f"  Screened (abstract):         {prisma_counts.get('records_screened', 0):>6}")
        print(f"  Full texts sought:           {prisma_counts.get('records_sought_fulltext', 0):>6}")
        print(f"  Full texts assessed:         {prisma_counts.get('records_assessed_fulltext', 0):>6}")
        print(f"  Studies included:            {len(output.included):>6}")
        print(f"  Studies excluded:            {len(output.excluded):>6}")
        print(f"  Uncertain:                   {len(output.uncertain):>6}")
        print(sep)
        print(f"  PRISMA flow:     {flow_path}")
        print(f"  Review report:   {report_path}")
        print(f"{sep}\n")
