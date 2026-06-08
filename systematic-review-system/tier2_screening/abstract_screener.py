"""
tier2_screening/abstract_screener.py
======================================
Abstract-level screening using per-criterion LLM calls and Noisy-OR fusion.

Flow for each candidate
-----------------------
1. For every MANDATORY inclusion criterion in the protocol:
   - Fill prompt template with PICO, criterion, title, abstract[:500]
   - Call LLM → {"satisfies": bool|"uncertain", "confidence": float}
   - Map to p_satisfy score (0–1)
2. Noisy-OR: p_include = 1 − ∏(1 − p_j)
3. Threshold: ≥0.70 → INCLUDE, ≤0.25 → EXCLUDE, else → UNCERTAIN
4. Build AbstractContext and return it

Concurrency: screen_batch runs up to 20 candidates simultaneously via
asyncio.Semaphore so the LLM rate limiter is respected.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.data_classes import (
    AbstractContext,
    CandidateRecord,
    CriterionType,
    Decision,
    ReviewProtocol,
    ScreeningTier,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH    = Path(__file__).parent.parent / "config" / "prompts" / "abstract_screening.txt"
_CONCURRENCY    = 25
_INCLUDE_THRESH = 0.70
_EXCLUDE_THRESH = 0.25
_UNCERTAIN_P    = 0.50

# p_satisfy caps when LLM says "false" — avoids overconfident exclusions
_FALSE_CAP = 0.30


def _load_template() -> str:
    return (
        "You are an expert medical screener performing FIRST-PASS ABSTRACT SCREENING.\n\n"
        "PICO:\n{pico_text}\n\n"
        "Criterion:\n{criterion_text}\n\n"
        "Title: {title}\nAbstract: {abstract}\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. Abstracts often omit details. Give the paper the benefit of the doubt.\n"
        "2. Missing information = 'Uncertain'. DO NOT exclude for missing data.\n"
        "3. Output ONLY raw JSON. No markdown blocks like ```json. Start with { and end with }.\n\n"
        '{"satisfies": true, "confidence": 0.8, "reasoning": "brief"}'
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


def _map_p_satisfy(satisfies: Any, confidence: float) -> float:
    """Convert LLM judgment to a probability of satisfying the criterion."""
    confidence = max(0.0, min(1.0, float(confidence)))
    if satisfies is True or satisfies == "true":
        return confidence
    if satisfies is False or satisfies == "false":
        return min(1.0 - confidence, _FALSE_CAP)
    # "uncertain" or unexpected value
    return _UNCERTAIN_P


def _noisy_or(p_values: List[float]) -> float:
    result = 1.0
    for p in p_values:
        result *= (1.0 - p)
    return 1.0 - result


def _decide(p_include: float) -> tuple[Decision, float]:
    if p_include >= _INCLUDE_THRESH:
        return Decision.INCLUDE,  p_include
    if p_include <= _EXCLUDE_THRESH:
        return Decision.EXCLUDE,  1.0 - p_include
    return Decision.UNCERTAIN, max(p_include, 1.0 - p_include)


class AbstractScreener:
    """Abstract-level screener using criterion-level LLM judgments."""

    async def screen_batch(
        self,
        candidates:     List[CandidateRecord],
        protocol:       ReviewProtocol,
        encoder:        Any,    # SharedEncoderService
        llm_client:     Any,    # LLMClient
        example_buffer: Any,    # ExampleBuffer  (unused here, available for subclasses)
    ) -> List[AbstractContext]:
        """Screen all candidates concurrently (up to _CONCURRENCY at a time)."""
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def _bounded(rec: CandidateRecord) -> AbstractContext:
            async with sem:
                return await self._screen_one(rec, protocol, encoder, llm_client)

        results = await asyncio.gather(*[_bounded(c) for c in candidates])
        logger.info(
            "AbstractScreener: screened %d candidates — include=%d exclude=%d uncertain=%d",
            len(results),
            sum(1 for r in results if r.abstract_decision == Decision.INCLUDE),
            sum(1 for r in results if r.abstract_decision == Decision.EXCLUDE),
            sum(1 for r in results if r.abstract_decision == Decision.UNCERTAIN),
        )
        return list(results)

    async def _screen_one(
        self,
        candidate:  CandidateRecord,
        protocol:   ReviewProtocol,
        encoder:    Any,
        llm_client: Any,
    ) -> AbstractContext:
        """Screen a single candidate; returns AbstractContext with UNCERTAIN on failure."""
        try:
            return await self._do_screen(candidate, protocol, encoder, llm_client)
        except Exception as exc:
            logger.warning(
                "AbstractScreener._screen_one failed for %s: %s",
                candidate.record_id, exc,
            )
            # Safe fallback: uncertain with zero embeddings
            zero = [0.0] * 128
            return AbstractContext(
                record_id                 = candidate.record_id,
                abstract_embedding        = zero,
                pico_embedding            = zero,
                retrieval_score           = 0.0,
                criterion_probabilities   = {},
                overall_include_probability = _UNCERTAIN_P,
                abstract_decision         = Decision.UNCERTAIN,
                abstract_confidence       = 0.5,
                screening_method          = ScreeningTier.TIER1_DIRECT.value,
                timestamp                 = datetime.now(),
            )

    async def _do_screen(
        self,
        candidate:  CandidateRecord,
        protocol:   ReviewProtocol,
        encoder:    Any,
        llm_client: Any,
    ) -> AbstractContext:
        pico_text  = _format_pico(protocol)
        title      = candidate.title or ""
        abstract   = (candidate.abstract or "")[:500]

        mandatory_criteria = [
            c for c in protocol.inclusion_criteria
            if c.type == CriterionType.MANDATORY
        ]

        criterion_probs: Dict[str, float] = {}

        for criterion in mandatory_criteria:
            prompt = _fill_template(
                _TEMPLATE,
                pico_text      = pico_text,
                criterion_text = criterion.text,
                title          = title,
                abstract       = abstract,
            )

            response = await llm_client.complete(
                prompt          = prompt,
                system          = "You are a precise systematic review screener. Reply only with the requested JSON.",
                model           = llm_client.GPT_MODEL,
                temperature     = 0.0,
                max_tokens      = 128,
                response_format = "json",
            )

            raw    = response.parsed_json
            parsed = raw if isinstance(raw, dict) else {}
            satisfies  = parsed.get("satisfies",  "uncertain")
            confidence = float(parsed.get("confidence", 0.5))

            criterion_probs[criterion.criterion_id] = _map_p_satisfy(satisfies, confidence)

        # If no mandatory criteria defined fall back to uncertain
        if not criterion_probs:
            p_include = _UNCERTAIN_P
        else:
            p_include = _noisy_or(list(criterion_probs.values()))

        decision, abs_confidence = _decide(p_include)

        # Embeddings
        abstract_emb = encoder.embed_abstract(title, candidate.abstract or "")
        pico_emb     = encoder.embed_pico(protocol.pico)

        return AbstractContext(
            record_id                   = candidate.record_id,
            abstract_embedding          = abstract_emb.tolist(),
            pico_embedding              = pico_emb.tolist(),
            retrieval_score             = 0.0,
            criterion_probabilities     = criterion_probs,
            overall_include_probability = p_include,
            abstract_decision           = decision,
            abstract_confidence         = abs_confidence,
            screening_method            = ScreeningTier.TIER1_DIRECT.value,
            timestamp                   = datetime.now(),
        )
