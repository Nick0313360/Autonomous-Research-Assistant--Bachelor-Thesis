"""
tier2_screening/decision_engine.py
=====================================
Aggregates per-criterion full-text screening results into a final per-paper
decision.

Inputs per paper
----------------
- ScreeningResult      : full-text criterion outcomes and p_include_final
- PICORecord           : extracted PICO with alignment score and mismatch flags
- AbstractContext       : abstract-stage decision and criterion probabilities
- ReviewProtocol       : for exclusion reason labelling

Decision logic
--------------
1. Start from ft_result.p_include_final.
2. If PICORecord has a mismatch flag, apply a 20 % downward adjustment.
3. Infer exclusion reason from the first failing criterion.
4. Threshold to INCLUDE / EXCLUDE / UNCERTAIN and return FinalDecision.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from models.data_classes import (
    AbstractContext,
    Decision,
    FinalDecision,
    PICORecord,
    ReviewProtocol,
    ScreeningResult,
)

logger = logging.getLogger(__name__)

_INCLUDE_THRESH    = 0.70
_EXCLUDE_THRESH    = 0.25
_PICO_MISMATCH_MUL = 0.80   # 20 % penalty for abstract/fulltext PICO misalignment


def _decide(p: float) -> Decision:
    if p >= _INCLUDE_THRESH:
        return Decision.INCLUDE
    if p <= _EXCLUDE_THRESH:
        return Decision.EXCLUDE
    return Decision.UNCERTAIN


class DecisionEngine:
    """Aggregates evidence from multiple screening stages into a FinalDecision."""

    async def decide_batch(
        self,
        ft_results:   List[ScreeningResult],
        pico_records: List[Optional[PICORecord]],
        contexts:     List[AbstractContext],
        protocol:     ReviewProtocol,
        llm_client:   Any,
    ) -> List[FinalDecision]:
        """
        Parameters
        ----------
        ft_results :   One ScreeningResult per document.
        pico_records : One PICORecord per document (or None).
        contexts :     AbstractContext objects indexed by record_id.
        protocol :     Review protocol for criterion text lookup.
        llm_client :   Reserved for future LLM-assisted arbitration.

        Returns
        -------
        List[FinalDecision] in the same order as ft_results.
        """
        context_map:   Dict[str, AbstractContext] = {c.record_id: c for c in contexts}
        criterion_map: Dict[str, Any]             = {
            c.criterion_id: c for c in protocol.inclusion_criteria
        }

        results: List[FinalDecision] = []
        for ft, pico in zip(ft_results, pico_records):
            ctx = context_map.get(ft.record_id)
            results.append(self._decide_one(ft, pico, ctx, criterion_map))

        n_inc = sum(1 for fd in results if fd.decision == Decision.INCLUDE)
        n_exc = sum(1 for fd in results if fd.decision == Decision.EXCLUDE)
        n_unc = sum(1 for fd in results if fd.decision == Decision.UNCERTAIN)
        logger.info(
            "DecisionEngine: %d total — include=%d exclude=%d uncertain=%d",
            len(results), n_inc, n_exc, n_unc,
        )
        return results

    # ------------------------------------------------------------------
    # Per-paper decision
    # ------------------------------------------------------------------

    @staticmethod
    def _decide_one(
        ft:            ScreeningResult,
        pico:          Optional[PICORecord],
        ctx:           Optional[AbstractContext],
        criterion_map: Dict[str, Any],
    ) -> FinalDecision:
        p = ft.p_include_final

        # PICO mismatch penalty
        if pico and "abstract_fulltext_pico_mismatch" in pico.pico_mismatch_flags:
            p_before = p
            p *= _PICO_MISMATCH_MUL
            logger.debug(
                "DecisionEngine: PICO mismatch penalty for %s (%.2f → %.2f)",
                ft.record_id, p_before, p,
            )

        p = max(0.0, min(1.0, p))

        criterion_probs: Dict[str, float] = {
            cr.criterion_id: cr.p_satisfy
            for cr in ft.criterion_results
        }

        decision = _decide(p)

        # Infer exclusion reason from the first failing mandatory criterion
        exclusion_reason       = ft.exclusion_reason
        exclusion_criterion_id = None
        if decision == Decision.EXCLUDE:
            for cr in ft.criterion_results:
                if cr.decision == Decision.EXCLUDE:
                    exclusion_criterion_id = cr.criterion_id
                    if not exclusion_reason:
                        crit = criterion_map.get(cr.criterion_id)
                        if crit:
                            exclusion_reason = crit.text[:80]
                    break

        explanation = ft.explanation or f"p_include={p:.2f}"

        return FinalDecision(
            decision                = decision,
            p_include_final         = p,
            criterion_probabilities = criterion_probs,
            explanation             = explanation,
            decision_record_id      = ft.record_id,
            exclusion_reason        = exclusion_reason,
            exclusion_criterion_id  = exclusion_criterion_id,
        )
