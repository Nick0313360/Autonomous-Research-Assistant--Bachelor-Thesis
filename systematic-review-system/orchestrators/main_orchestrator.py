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
import time
from pathlib import Path
from typing import Any, Optional

from models.data_classes import CandidateRecord, ReviewProtocol
from orchestrators.search_orchestrator import SearchOrchestrator
from orchestrators.screening_orchestrator import ScreeningOrchestrator, ScreeningOutput
from infrastructure.prisma_manager import PRISMAManager
from infrastructure.run_store import RunStore
from tier1_search.pubmed_connector import PubMedConnector
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
        encoder:          Any,
        llm_client:       Any,
        review_id:        str,
        output_dir:       str = "data/reports",
        run_store:        Optional[RunStore] = None,
        filter_threshold: float = 0.01,
    ) -> None:
        self._encoder    = encoder
        self._llm_client = llm_client
        self._review_id  = review_id
        self._run_store  = run_store

        # Shared PRISMAManager so both orchestrators write to the same state
        self._prisma = PRISMAManager(review_id)

        self._search_orch = SearchOrchestrator(
            llm_client = llm_client,
            review_id  = review_id,
        )
        self._screening_orch = ScreeningOrchestrator(
            encoder           = encoder,
            llm_client        = llm_client,
            review_id         = review_id,
            prisma            = self._prisma,
            filter_threshold  = filter_threshold,
        )
        self._data_extractor    = DataExtractionAgent()
        self._quality_assessor  = QualityAssessor()
        self._reporter          = PRISMAReporter(output_dir=str(Path(output_dir) / review_id))
        self._pubmed_connector  = PubMedConnector()

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
        _t0 = time.monotonic()
        candidates = await self._search_orch.run(protocol)
        if self._run_store:
            self._run_store.emit("pipeline.stage_complete", {
                "stage": "search",
                "elapsed_seconds": time.monotonic() - _t0,
            })

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
        # Canonical PMID injection (benchmark mode only)
        # ------------------------------------------------------------------
        if protocol.benchmark and protocol.benchmark.canonical_pmids_path:
            from pathlib import Path
            from evaluation.benchmark_evaluator import load_canonical_pmids, merge_with_canonical
            canonical_pmids = load_canonical_pmids(
                Path(protocol.benchmark.canonical_pmids_path)
            )
            logger.info(
                "BenchmarkMode: replacing autonomous candidates (%d) "
                "with canonical set (%d)",
                len(candidates),
                len(canonical_pmids),
            )
            n_before   = len(candidates)
            candidates = merge_with_canonical(candidates, canonical_pmids)
            n_added    = len(candidates) - n_before
            if n_added > 0:
                self._prisma.record_identification(n_added)

        # ---- Pre-fetch abstracts for stubs -------------------------
        stub_pmids = [
            c.pmid for c in candidates
            if getattr(c, 'title', '') == ''
            and (getattr(c, 'abstract', '') or '') == ''
            and getattr(c, 'pmid', None)
        ]
        if stub_pmids:
            logger.info(
                "BenchmarkMode: fetching abstracts for %d stub records "
                "from PubMed (this may take several minutes)...",
                len(stub_pmids)
            )
            fetched = await self._pubmed_connector.fetch_by_pmids(stub_pmids)
            filled = 0
            for candidate in candidates:
                if (getattr(candidate, 'pmid', None) in fetched
                        and getattr(candidate, 'title', '') == ''):
                    data = fetched[candidate.pmid]
                    candidate.title    = data['title']
                    candidate.abstract = data['abstract']
                    filled += 1
            logger.info(
                "BenchmarkMode: filled %d / %d stubs (%.1f%%); "
                "%d remain empty (PubMed returned no abstract)",
                filled,
                len(stub_pmids),
                100 * filled / len(stub_pmids) if stub_pmids else 0,
                len(stub_pmids) - filled,
            )
        # -------------------------------------------------------------

        # ---- m+ recovery (benchmark mode only) ----------------------
        if protocol.benchmark and protocol.benchmark.qrels_path:
            from evaluation.benchmark_evaluator import QrelsLoader
            qrels = QrelsLoader.load(
                Path(protocol.benchmark.qrels_path),
                topic_id=protocol.benchmark.topic_id,
            )
            positive_pmids   = {pmid for pmid, rel in qrels.items() if rel == 1}
            candidate_pmids  = {c.pmid for c in candidates if c.pmid}
            missing_pmids    = list(positive_pmids - candidate_pmids)
            if missing_pmids:
                fetched = await self._pubmed_connector.fetch_by_pmids(missing_pmids)
                recovered, unfetchable = 0, 0
                for pmid in missing_pmids:
                    if pmid in fetched:
                        data = fetched[pmid]
                        candidates.append(CandidateRecord(
                            record_id       = f"recovery_{pmid}",
                            pmid            = pmid,
                            title           = data["title"],
                            abstract        = data["abstract"],
                            source_database = "m_plus_recovery",
                        ))
                        recovered += 1
                    else:
                        unfetchable += 1
                logger.info(
                    "BenchmarkMode m+ recovery: fetched %d missing positives "
                    "from PubMed, %d unfetchable",
                    recovered, unfetchable,
                )
        # -------------------------------------------------------------

        # ------------------------------------------------------------------
        # Phase 2: Screening
        # ------------------------------------------------------------------
        logger.info("MainOrchestrator: Phase 2 — Screening (%d candidates)", len(candidates))
        _t0 = time.monotonic()
        if protocol.benchmark and protocol.benchmark.canonical_pmids_path:
            self._screening_orch._filter_threshold = 0.0
            logger.info(
                "BenchmarkMode: hybrid filter threshold set to 0.0 — "
                "all canonical papers will be screened"
            )
        screening_output: ScreeningOutput = await self._screening_orch.run(
            candidates, protocol
        )
        if self._run_store:
            self._run_store.emit("pipeline.stage_complete", {
                "stage": "screening",
                "elapsed_seconds": time.monotonic() - _t0,
            })
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
            _t0 = time.monotonic()
            extracted_data = await self._data_extractor.extract_batch(
                documents  = included_docs,
                protocol   = protocol,
                llm_client = self._llm_client,
            )
            if self._run_store:
                self._run_store.emit("pipeline.stage_complete", {
                    "stage": "extraction",
                    "elapsed_seconds": time.monotonic() - _t0,
                })
        else:
            extracted_data = []

        # ------------------------------------------------------------------
        # Phase 4: Quality assessment (stub)
        # ------------------------------------------------------------------
        if included_docs:
            logger.info("MainOrchestrator: Phase 4 — Quality assessment")
            _t0 = time.monotonic()
            quality_data = await self._quality_assessor.assess_batch(
                documents      = included_docs,
                extracted_data = extracted_data,
                protocol       = protocol,
                llm_client     = self._llm_client,
            )
            if self._run_store:
                self._run_store.emit("pipeline.stage_complete", {
                    "stage": "quality_assessment",
                    "elapsed_seconds": time.monotonic() - _t0,
                })
        else:
            quality_data = []

        # ------------------------------------------------------------------
        # Phase 5 & 6: PRISMA reporting
        # ------------------------------------------------------------------
        prisma_counts = self._prisma.generate_prisma_counts()

        flow_path   = self._reporter.generate_flow_diagram(prisma_counts)
        cand_map = {c.record_id: c for c in candidates}
        included_studies_data = [
            {
                "record_id": fd.decision_record_id,
                "pmid":      getattr(cand_map.get(fd.decision_record_id), "pmid",     None),
                "title":     getattr(cand_map.get(fd.decision_record_id), "title",    None) or "",
                "abstract":  getattr(cand_map.get(fd.decision_record_id), "abstract", None) or "",
            }
            for fd in screening_output.included
        ]
        report_path = await self._reporter.generate_review_report(
            protocol            = protocol,
            included_studies    = included_studies_data,
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

        # ------------------------------------------------------------------
        # Benchmark evaluation (runs only when protocol.benchmark is set)
        # ------------------------------------------------------------------
        if protocol.benchmark and protocol.benchmark.qrels_path:
            import json
            from evaluation.benchmark_evaluator import QrelsLoader, BenchmarkEvaluator
            from models.data_classes import Decision, FinalDecision as _FD

            qrels = QrelsLoader().load(
                Path(protocol.benchmark.qrels_path),
                topic_id=protocol.benchmark.topic_id,
            )
            evaluator = BenchmarkEvaluator(qrels, alpha=0.15)

            # Build a decision for every candidate that entered Phase 2 so that
            # abstract-excluded and hybrid-filtered papers are not silently
            # treated as true negatives by the evaluator.
            included_pmids  = {fd.pmid for fd in screening_output.included  if fd.pmid}
            uncertain_pmids = {fd.pmid for fd in screening_output.uncertain if fd.pmid}
            all_screening_decisions: list[_FD] = []
            for c in candidates:
                if not c.pmid:
                    continue
                if c.pmid in included_pmids:
                    dec = Decision.INCLUDE
                elif c.pmid in uncertain_pmids:
                    dec = Decision.UNCERTAIN
                else:
                    dec = Decision.EXCLUDE
                all_screening_decisions.append(_FD(
                    decision                = dec,
                    p_include_final         = 1.0 if dec == Decision.INCLUDE else 0.0,
                    criterion_probabilities = {},
                    explanation             = "",
                    decision_record_id      = c.record_id,
                    pmid                    = c.pmid,
                ))

            result = evaluator.evaluate(all_screening_decisions)
            _stats_path = self._reporter._output_dir / "run_stats.json"
            _stats_path.parent.mkdir(parents=True, exist_ok=True)
            with open(_stats_path, "w") as _f:
                json.dump(
                    {"topic_id": protocol.benchmark.topic_id, "benchmark_eval": result},
                    _f,
                    indent=2,
                )
            logger.info("BenchmarkMode: results written to %s", _stats_path)
            if self._run_store:
                self._run_store.emit("benchmark.evaluation", result)
                self._run_store.write_run_stats({
                    "topic_id": protocol.benchmark.topic_id,
                    "benchmark_eval": result,
                })
            print(json.dumps(result, indent=2))

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
