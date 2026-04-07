"""Module 2 — Validation (ScreeningEvaluator)"""

from __future__ import annotations

from typing import List, Tuple

from models import Paper, SearchQuery
from prisma_log import PrismaLog
from orchestrator import ScreeningOrchestrator


class ScreeningEvaluator:
    """
    Module 2::Validation::ScreeningEvaluator

    Measures pipeline performance on held-out SYNERGY reviews (test split).
    METRIC: WSS@95 (Work Saved over Sampling at 95% recall)

    DATA IN:
      papersWithLabels — List[Tuple[Paper, int]] (label: 1=include, 0=exclude)
      query            — SearchQuery for this review
      pipeline         — ScreeningOrchestrator instance

    DATA OUT:
      dict with wss_at_95, recall_at_stop, n_total, n_true_include,
      n_found_include, n_screened_to_95
    """

    def evaluate(
        self,
        papersWithLabels: List[Tuple[Paper, int]],
        query: SearchQuery,
        pipeline: ScreeningOrchestrator,
    ) -> dict:
        papers = [p for p, _ in papersWithLabels]
        labelMap = {id(p): lbl for p, lbl in papersWithLabels}
        trueInc = sum(lbl for _, lbl in papersWithLabels)

        result = pipeline.runScreening(papers, query)
        PrismaLog.resetInstance()

        # Priority ordering: included > uncertain > excluded
        ordered = result.includedPapers + result.uncertainPapers + result.excludedPapers

        found = 0
        target = 0.95 * trueInc
        screened95 = len(ordered)

        for i, paper in enumerate(ordered):
            found += labelMap.get(id(paper), 0)
            if found >= target:
                screened95 = i + 1
                break

        wss = round((len(ordered) - screened95) / max(len(ordered), 1), 4)
        recall_at_stop = round(found / max(trueInc, 1), 4)

        return {
            "wss_at_95": wss,
            "recall_at_stop": recall_at_stop,
            "n_total": len(ordered),
            "n_true_include": trueInc,
            "n_found_include": int(found),
            "n_screened_to_95": screened95,
        }
