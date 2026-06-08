"""
tier2_screening/fulltext_screener.py
=======================================
Full-text eligibility screening with token-count-based routing.

Three screening tiers
---------------------
_tier1_screen  (< 3 000 tokens)
    Single LLM call per criterion using concatenated Methods+Results text.
    Evidence spans are verified by SpanVerifier; unverified spans trigger a
    hallucination flag and a 70 % penalty on p_satisfy.

_tier2_screen  (3 000 – 12 000 tokens)
    Embedding-based cross-attention over section embeddings.
    Combines dense retrieval scores with the abstract-stage priors stored in
    AbstractContext.criterion_probabilities.
    No LLM call — fast, recall-safe, suitable for medium-length papers.

_tier3_screen  (> 12 000 tokens)
    Delegates to CriterionAwareRAG for retrieve-then-read over long documents.
    Falls back to _tier2_screen if CriterionAwareRAG is not yet implemented.

Concurrency: screen_batch runs up to 5 documents simultaneously.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from models.data_classes import (
    AbstractContext,
    CriterionResult,
    CriterionType,
    Decision,
    ReviewProtocol,
    ScreeningResult,
    ScreeningTier,
    SectionLabel,
    StructuredDocument,
)

logger = logging.getLogger(__name__)

_CONCURRENCY       = 20
_TIER1_THRESHOLD   = 3_000     # tokens
_TIER2_THRESHOLD   = 12_000    # tokens
_INCLUDE_THRESH    = 0.70
_EXCLUDE_THRESH    = 0.25

_PROMPT_PATH = (
    Path(__file__).parent.parent / "config" / "prompts" / "criterion_check.txt"
)

# p_satisfy for a false+high-confidence LLM judgment (before hallucination penalty)
_FALSE_CAP         = 0.30
# Multiplicative penalty when evidence span fails verification
_HALLUCINATION_MUL = 0.30


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _load_template() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "You are a systematic review screener.\n\n"
        "PICO:\n{pico_text}\n\n"
        "Criterion:\n{criterion_text}\n\n"
        "Context:\n{context_text}\n\n"
        'Reply with JSON only: {"satisfies": true|false, "confidence": <0.0-1.0>, '
        '"evidence_span": "<verbatim quote or empty>", "reasoning": "<one sentence>"}'
    )


_TEMPLATE = _load_template()


def _fill_template(template: str, **kwargs: str) -> str:
    """Safely substitute named placeholders without interpreting other braces."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def _format_pico(protocol: ReviewProtocol) -> str:
    p = protocol.pico
    return (
        f"Population: {p.population}\n"
        f"Intervention: {p.intervention}\n"
        f"Comparator: {p.comparator}\n"
        f"Outcome: {p.outcome}\n"
        f"Study design: {p.study_design}"
    )


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def _decide(p_include: float) -> tuple[Decision, float]:
    if p_include >= _INCLUDE_THRESH:
        return Decision.INCLUDE, p_include
    if p_include <= _EXCLUDE_THRESH:
        return Decision.EXCLUDE, 1.0 - p_include
    return Decision.UNCERTAIN, max(p_include, 1.0 - p_include)


# ---------------------------------------------------------------------------
# FullTextScreener
# ---------------------------------------------------------------------------

class FullTextScreener:
    """Full-text screener with three token-count-based routing tiers."""

    async def screen_batch(
        self,
        documents:       List[StructuredDocument],
        contexts:        List[AbstractContext],
        protocol:        ReviewProtocol,
        encoder:         Any,     # SharedEncoderService
        llm_client:      Any,     # LLMClient
        verifier:        Any,     # SpanVerifier
    ) -> List[ScreeningResult]:
        """
        Screen all documents concurrently (up to _CONCURRENCY at a time).

        Parameters
        ----------
        documents  : Full-text parsed documents.
        contexts   : AbstractContext objects indexed by record_id.
        protocol   : Review protocol with PICO and inclusion criteria.
        encoder    : SharedEncoderService for embedding operations.
        llm_client : LLMClient instance.
        verifier   : SpanVerifier for grounding checks.

        Returns
        -------
        List[ScreeningResult] in the same order as *documents*.
        """
        context_map: Dict[str, AbstractContext] = {c.record_id: c for c in contexts}
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def _bounded(doc: StructuredDocument) -> ScreeningResult:
            ctx = context_map.get(doc.record_id)
            async with sem:
                return await self._screen_one(
                    doc, ctx, protocol, llm_client, encoder, verifier
                )

        results = await asyncio.gather(*[_bounded(d) for d in documents])
        logger.info(
            "FullTextScreener: screened %d docs — include=%d exclude=%d uncertain=%d",
            len(results),
            sum(1 for r in results if r.final_decision == Decision.INCLUDE),
            sum(1 for r in results if r.final_decision == Decision.EXCLUDE),
            sum(1 for r in results if r.final_decision == Decision.UNCERTAIN),
        )
        return list(results)

    async def _screen_one(
        self,
        document:         StructuredDocument,
        abstract_context: Optional[AbstractContext],
        protocol:         ReviewProtocol,
        llm_client:       Any,
        encoder:          Any,
        verifier:         Any,
    ) -> ScreeningResult:
        """Route to the appropriate tier based on token count."""
        try:
            tokens = document.token_count

            if tokens < _TIER1_THRESHOLD:
                criterion_results = await self._tier1_screen(
                    document, abstract_context, protocol, llm_client, verifier
                )
                tier = ScreeningTier.TIER1_DIRECT
            elif tokens <= _TIER2_THRESHOLD:
                criterion_results = self._tier2_screen(
                    document, abstract_context, protocol, encoder
                )
                tier = ScreeningTier.TIER2_HIERARCHICAL
            else:
                criterion_results = await self._tier3_screen(
                    document, abstract_context, protocol, encoder, llm_client, verifier
                )
                tier = ScreeningTier.TIER3_RAG

        except Exception as exc:
            logger.warning(
                "FullTextScreener._screen_one failed for %s: %s",
                document.record_id, exc,
            )
            return self._uncertain_result(
                document.record_id,
                ScreeningTier.TIER1_DIRECT,
                reason=str(exc),
            )

        abstract_decision = (
            abstract_context.abstract_decision if abstract_context else None
        )
        return self._build_result(document.record_id, criterion_results, tier, abstract_decision)

    # ------------------------------------------------------------------
    # Tier 1: short documents — direct LLM criterion check
    # ------------------------------------------------------------------

    async def _tier1_screen(
        self,
        document:         StructuredDocument,
        abstract_context: Optional[AbstractContext],
        protocol:         ReviewProtocol,
        llm_client:       Any,
        verifier:         Any,
    ) -> List[CriterionResult]:
        pico_text = _format_pico(protocol)
        mandatory = [
            c for c in protocol.inclusion_criteria
            if c.type == CriterionType.MANDATORY
        ]

        # Build context text from Methods + Results (capped at 4 000 chars)
        context_text = (
            document.sections.get(SectionLabel.METHODS.value, "")
            + " "
            + document.sections.get(SectionLabel.RESULTS.value, "")
        )[:4000]

        results: List[CriterionResult] = []

        for criterion in mandatory:
            prompt = _fill_template(
                _TEMPLATE,
                pico_text      = pico_text,
                criterion_text = criterion.text,
                context_text   = context_text,
            )

            response = await llm_client.complete(
                prompt          = prompt,
                system          = (
                    "You are a precise systematic review screener. "
                    "Reply only with the requested JSON."
                ),
                model           = llm_client.GPT_MODEL,
                temperature     = 0.0,
                max_tokens      = 256,
                response_format = "json",
            )

            parsed     = response.parsed_json or {}
            satisfies  = parsed.get("satisfies",     False)
            confidence = float(parsed.get("confidence",  0.5))
            span       = str(parsed.get("evidence_span", "")).strip()
            confidence = max(0.0, min(1.0, confidence))

            # Compute p_satisfy
            if satisfies is True or satisfies == "true":
                p_satisfy = confidence
            else:
                p_satisfy = min(1.0 - confidence, _FALSE_CAP)

            # Span verification
            hallucination = False
            verified      = False
            if span:
                verified = verifier.verify(span, document)
                if not verified:
                    hallucination = True
                    p_satisfy    *= _HALLUCINATION_MUL
                    logger.debug(
                        "FullTextScreener: hallucination flag for %s / %s",
                        document.record_id, criterion.criterion_id,
                    )

            # Infer source section (which section the span came from)
            source_section = self._infer_section(span, document)

            cr_decision, _ = _decide(p_satisfy)
            results.append(CriterionResult(
                criterion_id         = criterion.criterion_id,
                p_satisfy            = p_satisfy,
                decision             = cr_decision,
                evidence_span        = span or None,
                evidence_span_verified = verified,
                source_section       = source_section,
                hallucination_flag   = hallucination,
                llm_raw_response     = response.content,
            ))

        return results

    # ------------------------------------------------------------------
    # Tier 2: medium documents — embedding cross-attention + abstract prior
    # ------------------------------------------------------------------

    def _tier2_screen(
        self,
        document:         StructuredDocument,
        abstract_context: Optional[AbstractContext],
        protocol:         ReviewProtocol,
        encoder:          Any,
    ) -> List[CriterionResult]:
        mandatory = [
            c for c in protocol.inclusion_criteria
            if c.type == CriterionType.MANDATORY
        ]

        # Build section embedding matrix (shape: [n_sections, embed_dim])
        sec_emb_map = document.section_embeddings   # str → List[float]
        if not sec_emb_map:
            # No embeddings available — fall back to abstract priors only
            return self._prior_only_results(mandatory, abstract_context)

        sec_labels   = list(sec_emb_map.keys())
        sec_matrix   = np.array(
            [sec_emb_map[k] for k in sec_labels], dtype=np.float32
        )  # (n_sections, dim)

        results: List[CriterionResult] = []

        for criterion in mandatory:
            # Embed the criterion text into the section embedding space
            try:
                criterion_emb = encoder.embed_section(
                    criterion.text, SectionLabel.OTHER
                ).astype(np.float32)          # (dim,)
            except Exception as exc:
                logger.warning(
                    "FullTextScreener._tier2_screen: embed_section failed: %s", exc
                )
                p_satisfy = self._abstract_prior(criterion.criterion_id, abstract_context)
                cr_decision, _ = _decide(p_satisfy)
                results.append(CriterionResult(
                    criterion_id = criterion.criterion_id,
                    p_satisfy    = p_satisfy,
                    decision     = cr_decision,
                ))
                continue

            embed_dim = criterion_emb.shape[0]

            # Cross-attention: score each section against the criterion
            raw_scores = sec_matrix.dot(criterion_emb) / np.sqrt(embed_dim)
            weights    = _softmax(raw_scores)            # (n_sections,)

            # Evidence vector: weighted sum of section embeddings
            # evidence_vector = weights @ sec_matrix   # (dim,) — available for MLP

            # Proxy score: max attention weight (how strongly the criterion
            # aligns with any single section) combined with abstract-stage prior
            max_weight    = float(np.max(weights))
            abstract_prior = self._abstract_prior(criterion.criterion_id, abstract_context)

            p_satisfy = (max_weight + abstract_prior) / 2.0
            p_satisfy = max(0.0, min(1.0, p_satisfy))

            cr_decision, _ = _decide(p_satisfy)

            # Best-matching section label for reporting
            best_sec_idx   = int(np.argmax(weights))
            best_sec_value = sec_labels[best_sec_idx]
            try:
                source_section = SectionLabel(best_sec_value)
            except ValueError:
                source_section = SectionLabel.OTHER

            results.append(CriterionResult(
                criterion_id   = criterion.criterion_id,
                p_satisfy      = p_satisfy,
                decision       = cr_decision,
                source_section = source_section,
            ))

        return results

    # ------------------------------------------------------------------
    # Tier 3: long documents — CriterionAwareRAG
    # ------------------------------------------------------------------

    async def _tier3_screen(
        self,
        document:         StructuredDocument,
        abstract_context: Optional[AbstractContext],
        protocol:         ReviewProtocol,
        encoder:          Any,
        llm_client:       Any,
        verifier:         Any,
    ) -> List[CriterionResult]:
        """
        Delegate to CriterionAwareRAG.  Falls back to _tier2_screen if the
        RAG module is not yet implemented.
        """
        try:
            from tier2_screening.criterion_aware_rag import CriterionAwareRAG  # type: ignore
            rag = CriterionAwareRAG()
            mandatory = [
                c for c in protocol.inclusion_criteria
                if c.type == CriterionType.MANDATORY
            ]
            results: List[CriterionResult] = []
            for criterion in mandatory:
                cr = await rag.screen_criterion(
                    criterion        = criterion,
                    document         = document,
                    abstract_context = abstract_context,
                    protocol         = protocol,
                    encoder          = encoder,
                    llm_client       = llm_client,
                    verifier         = verifier,
                )
                results.append(cr)
            return results
        except (ImportError, AttributeError):
            logger.debug(
                "FullTextScreener: CriterionAwareRAG not available, "
                "falling back to tier2 for %s",
                document.record_id,
            )
            return self._tier2_screen(
                document, abstract_context, protocol, encoder
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _abstract_prior(
        criterion_id:    str,
        abstract_context: Optional[AbstractContext],
    ) -> float:
        if abstract_context is None:
            return 0.5
        return abstract_context.criterion_probabilities.get(criterion_id, 0.5)

    @staticmethod
    def _prior_only_results(
        mandatory:        list,
        abstract_context: Optional[AbstractContext],
    ) -> List[CriterionResult]:
        results = []
        for criterion in mandatory:
            p = (
                abstract_context.criterion_probabilities.get(criterion.criterion_id, 0.5)
                if abstract_context else 0.5
            )
            decision, _ = _decide(p)
            results.append(CriterionResult(
                criterion_id = criterion.criterion_id,
                p_satisfy    = p,
                decision     = decision,
            ))
        return results

    @staticmethod
    def _infer_section(span: str, document: StructuredDocument) -> SectionLabel:
        """Return the SectionLabel of the section that contains *span*."""
        if not span:
            return SectionLabel.OTHER
        for label_val, text in document.sections.items():
            if span in text:
                try:
                    return SectionLabel(label_val)
                except ValueError:
                    return SectionLabel.OTHER
        return SectionLabel.OTHER

    @staticmethod
    def _build_result(
        record_id:         str,
        criterion_results: List[CriterionResult],
        tier:              ScreeningTier,
        abstract_decision: Optional[Decision] = None,
    ) -> ScreeningResult:
        """Aggregate criterion results into a ScreeningResult."""
        if not criterion_results:
            p_final = 0.5
        else:
            # Noisy-OR: P(include) = 1 − ∏(1 − p_j)
            complement = 1.0
            for cr in criterion_results:
                complement *= (1.0 - cr.p_satisfy)
            p_final = 1.0 - complement

        p_final = max(0.0, min(1.0, p_final))
        decision, _ = _decide(p_final)

        # Conflict guard: abstract said INCLUDE but full-text is borderline EXCLUDE
        # → flag for human review instead of hard-excluding
        if (
            decision == Decision.EXCLUDE
            and p_final > 0.40
            and abstract_decision == Decision.INCLUDE
        ):
            decision = Decision.UNCERTAIN

        explanation_parts = [
            f"{cr.criterion_id}: p={cr.p_satisfy:.2f}"
            + (" [hallucinated]" if cr.hallucination_flag else "")
            for cr in criterion_results
        ]
        explanation = "; ".join(explanation_parts) or "no mandatory criteria"

        return ScreeningResult(
            record_id         = record_id,
            screening_tier    = tier,
            criterion_results = criterion_results,
            final_decision    = decision,
            p_include_final   = p_final,
            explanation       = explanation,
            timestamp         = datetime.now(),
        )

    @staticmethod
    def _uncertain_result(
        record_id: str,
        tier:      ScreeningTier,
        reason:    str = "",
    ) -> ScreeningResult:
        return ScreeningResult(
            record_id         = record_id,
            screening_tier    = tier,
            criterion_results = [],
            final_decision    = Decision.UNCERTAIN,
            p_include_final   = 0.5,
            explanation       = f"screening_failed: {reason}" if reason else "screening_failed",
            timestamp         = datetime.now(),
        )
