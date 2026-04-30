"""
orchestrators/screening_orchestrator.py
==========================================
Drives the multi-stage screening pipeline for a set of candidates.

Pipeline stages
---------------
1. Encode PICO → pico_embedding
2. HybridRetriever: build indices, rank, filter
3. AbstractScreener: screen above-threshold candidates
4. FullTextRetriever: retrieve PDFs/XML for non-excluded papers
5. DocumentParser: parse each retrieved document
6. FullTextScreener: full-text criterion check (tier-routed)
7. PICOExtractor: extract PICO elements per included document
8. DecisionEngine: aggregate into FinalDecision per paper
9. Update PRISMAManager at each stage
10. Return ScreeningOutput
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.data_classes import (
    AbstractContext,
    CandidateRecord,
    Decision,
    FinalDecision,
    PICORecord,
    PRISMAState,
    ReviewProtocol,
    ScreeningResult,
    StructuredDocument,
)
from tier2_screening.abstract_screener import AbstractScreener
from tier2_screening.decision_engine import DecisionEngine
from tier2_screening.document_parser import DocumentParser
from tier2_screening.example_buffer import ExampleBuffer
from tier2_screening.fulltext_retriever import FullTextRetriever
from tier2_screening.fulltext_screener import FullTextScreener
from tier2_screening.hybrid_retriever import HybridRetriever
from tier2_screening.pico_extractor import PICOExtractor
from tier2_screening.span_verifier import SpanVerifier
from infrastructure.prisma_manager import PRISMAManager

logger = logging.getLogger(__name__)


@dataclass
class ScreeningOutput:
    """Aggregated result of the full screening pipeline."""
    included:         List[FinalDecision]  = field(default_factory=list)
    excluded:         List[FinalDecision]  = field(default_factory=list)
    uncertain:        List[FinalDecision]  = field(default_factory=list)
    included_docs:    List[StructuredDocument] = field(default_factory=list)
    prisma_snapshot:  Optional[PRISMAState]    = None


class ScreeningOrchestrator:
    """
    Runs the complete screening pipeline and returns a ScreeningOutput.

    Parameters
    ----------
    encoder :    SharedEncoderService
    llm_client : LLMClient
    review_id :  str  — used by FullTextRetriever for file storage and
                        by PRISMAManager for audit logging.
    prisma :     Optional PRISMAManager.  If None, a new one is created.
    """

    def __init__(
        self,
        encoder:         Any,
        llm_client:      Any,
        review_id:       str,
        prisma:          Optional[PRISMAManager] = None,
        calibrator_path: Optional[Path] = None,
    ) -> None:
        self._encoder          = encoder
        self._llm_client       = llm_client
        self._review_id        = review_id
        self._prisma           = prisma or PRISMAManager(review_id)
        self._hybrid_retriever = HybridRetriever(calibrator_path=calibrator_path)
        self._abstract_screener = AbstractScreener()
        self._example_buffer   = ExampleBuffer(encoder)
        self._fulltext_retriever = FullTextRetriever(review_id)
        self._document_parser  = DocumentParser()
        self._fulltext_screener = FullTextScreener()
        self._span_verifier    = SpanVerifier()
        self._pico_extractor   = PICOExtractor()
        self._decision_engine  = DecisionEngine()

    async def run(
        self,
        candidates: List[CandidateRecord],
        protocol:   ReviewProtocol,
    ) -> ScreeningOutput:
        """
        Parameters
        ----------
        candidates : Deduplicated CandidateRecords from SearchOrchestrator.
        protocol :   Review protocol.

        Returns
        -------
        ScreeningOutput
        """
        if not candidates:
            logger.warning("ScreeningOrchestrator: empty candidate list")
            return ScreeningOutput(prisma_snapshot=self._prisma.state)

        # ------------------------------------------------------------------
        # Stage 1: encode PICO
        # ------------------------------------------------------------------
        pico_embedding = self._encoder.embed_pico(protocol.pico)
        pico_query_text = (
            f"{protocol.pico.population} {protocol.pico.intervention} "
            f"{protocol.pico.comparator} {protocol.pico.outcome}"
        )

        # ------------------------------------------------------------------
        # Stage 2: hybrid retrieval ranking + filter
        # ------------------------------------------------------------------
        self._hybrid_retriever.build_indices(candidates, self._encoder)
        ranked = self._hybrid_retriever.rank(candidates, pico_embedding, pico_query_text)
        above, below = self._hybrid_retriever.filter(ranked)

        logger.info(
            "ScreeningOrchestrator: hybrid filter — %d above threshold, %d below",
            len(above), len(below),
        )

        # ------------------------------------------------------------------
        # Stage 3: abstract screening
        # ------------------------------------------------------------------
        above_candidates = [r.candidate for r in above]
        contexts: List[AbstractContext] = await self._abstract_screener.screen_batch(
            candidates     = above_candidates,
            protocol       = protocol,
            encoder        = self._encoder,
            llm_client     = self._llm_client,
            example_buffer = self._example_buffer,
        )

        n_abs_inc = sum(1 for c in contexts if c.abstract_decision != Decision.EXCLUDE)
        n_abs_exc = sum(1 for c in contexts if c.abstract_decision == Decision.EXCLUDE)
        self._prisma.record_abstract_screening(included=n_abs_inc, excluded=n_abs_exc)
        logger.info(
            "ScreeningOrchestrator: abstract screening — include/uncertain=%d exclude=%d",
            n_abs_inc, n_abs_exc,
        )

        # ------------------------------------------------------------------
        # Stage 4: full-text retrieval (non-excluded only)
        # ------------------------------------------------------------------
        include_contexts = [
            c for c in contexts if c.abstract_decision != Decision.EXCLUDE
        ]
        candidate_map: Dict[str, CandidateRecord] = {
            c.record_id: c for c in candidates
        }

        retrieval_results = await self._fulltext_retriever.retrieve_batch(
            contexts   = include_contexts,
            candidates = list(candidate_map.values()),
        )

        n_retrieved  = sum(1 for r in retrieval_results if r.success)
        n_failed     = sum(1 for r in retrieval_results if not r.success)
        self._prisma.record_fulltext_retrieval(retrieved=n_retrieved, failed=n_failed)

        # ------------------------------------------------------------------
        # Stage 5: document parsing
        # ------------------------------------------------------------------
        successful_retrievals = [r for r in retrieval_results if r.success]
        documents: List[StructuredDocument] = []
        for ret_result in successful_retrievals:
            try:
                doc = self._document_parser.parse(ret_result, self._encoder)
                documents.append(doc)
            except Exception as exc:
                logger.warning(
                    "ScreeningOrchestrator: parse failed for %s: %s",
                    ret_result.record_id, exc,
                )

        logger.info(
            "ScreeningOrchestrator: parsed %d/%d documents",
            len(documents), n_retrieved,
        )

        if not documents:
            logger.warning(
                "ScreeningOrchestrator: no documents parsed — "
                "falling back to abstract screening decisions for %d papers",
                len(include_contexts),
            )
            fallback_decisions = self._abstract_fallback_decisions(include_contexts)
            n_fb_inc = sum(1 for fd in fallback_decisions if fd.decision == Decision.INCLUDE)
            n_fb_exc = sum(1 for fd in fallback_decisions if fd.decision == Decision.EXCLUDE)
            n_fb_unc = sum(1 for fd in fallback_decisions if fd.decision == Decision.UNCERTAIN)
            self._prisma.record_fulltext_screening(
                included     = n_fb_inc,
                excluded     = n_fb_exc,
                reasons_dict = {"full_text_unavailable": n_fb_exc},
            )
            self._prisma.record_inclusion(n_fb_inc)
            logger.info(
                "ScreeningOrchestrator: abstract fallback — include=%d exclude=%d uncertain=%d",
                n_fb_inc, n_fb_exc, n_fb_unc,
            )
            return self._build_output(fallback_decisions, [], [])

        # Build context lookup for the documents we have
        context_map: Dict[str, AbstractContext] = {c.record_id: c for c in contexts}
        doc_contexts = [context_map.get(d.record_id) for d in documents]

        # ------------------------------------------------------------------
        # Stage 6: full-text screening
        # ------------------------------------------------------------------
        ft_results: List[ScreeningResult] = await self._fulltext_screener.screen_batch(
            documents  = documents,
            contexts   = [c for c in doc_contexts if c is not None],
            protocol   = protocol,
            encoder    = self._encoder,
            llm_client = self._llm_client,
            verifier   = self._span_verifier,
        )

        # ------------------------------------------------------------------
        # Stage 7: PICO extraction
        # ------------------------------------------------------------------
        pico_records: List[Optional[PICORecord]] = []
        for doc, ctx in zip(documents, doc_contexts):
            if ctx is None:
                pico_records.append(None)
                continue
            try:
                pico_rec = await self._pico_extractor.extract(
                    document         = doc,
                    protocol         = protocol,
                    abstract_context = ctx,
                    encoder          = self._encoder,
                    llm_client       = self._llm_client,
                )
                pico_records.append(pico_rec)
            except Exception as exc:
                logger.warning(
                    "ScreeningOrchestrator: PICO extraction failed for %s: %s",
                    doc.record_id, exc,
                )
                pico_records.append(None)

        # ------------------------------------------------------------------
        # Stage 8: decision engine
        # ------------------------------------------------------------------
        valid_contexts = [c for c in doc_contexts if c is not None]
        final_decisions: List[FinalDecision] = await self._decision_engine.decide_batch(
            ft_results   = ft_results,
            pico_records = pico_records,
            contexts     = valid_contexts,
            protocol     = protocol,
            llm_client   = self._llm_client,
        )

        # ------------------------------------------------------------------
        # Stage 9: PRISMA fulltext screening update
        # ------------------------------------------------------------------
        n_ft_inc = sum(1 for fd in final_decisions if fd.decision == Decision.INCLUDE)
        n_ft_exc = sum(1 for fd in final_decisions if fd.decision == Decision.EXCLUDE)
        reasons: Dict[str, int] = {}
        for fd in final_decisions:
            if fd.decision == Decision.EXCLUDE and fd.exclusion_reason:
                r = fd.exclusion_reason[:60]
                reasons[r] = reasons.get(r, 0) + 1

        self._prisma.record_fulltext_screening(
            included     = n_ft_inc,
            excluded     = n_ft_exc,
            reasons_dict = reasons,
        )
        self._prisma.record_inclusion(n_ft_inc)

        return self._build_output(final_decisions, documents, documents)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _abstract_fallback_decisions(
        contexts: List[AbstractContext],
    ) -> List[FinalDecision]:
        """
        Convert abstract-stage decisions to FinalDecision objects when full-text
        retrieval fails for all candidates.  Used so the final report is not empty.
        """
        decisions: List[FinalDecision] = []
        for ctx in contexts:
            decisions.append(FinalDecision(
                decision                 = ctx.abstract_decision,
                p_include_final          = ctx.overall_include_probability,
                criterion_probabilities  = ctx.criterion_probabilities,
                explanation              = "abstract-only screening (full text unavailable)",
                decision_record_id       = ctx.record_id,
                exclusion_reason         = (
                    "full text could not be retrieved" if ctx.abstract_decision == Decision.EXCLUDE
                    else None
                ),
            ))
        return decisions

    def _build_output(
        self,
        final_decisions: List[FinalDecision],
        documents:       List[StructuredDocument],
        all_docs:        List[StructuredDocument],
    ) -> ScreeningOutput:
        included_ids = {
            fd.decision_record_id
            for fd in final_decisions
            if fd.decision == Decision.INCLUDE
        }
        included_docs = [d for d in all_docs if d.record_id in included_ids]

        return ScreeningOutput(
            included      = [fd for fd in final_decisions if fd.decision == Decision.INCLUDE],
            excluded      = [fd for fd in final_decisions if fd.decision == Decision.EXCLUDE],
            uncertain     = [fd for fd in final_decisions if fd.decision == Decision.UNCERTAIN],
            included_docs = included_docs,
            prisma_snapshot = self._prisma.state,
        )

    @property
    def prisma(self) -> PRISMAManager:
        return self._prisma
