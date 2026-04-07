from __future__ import annotations

from typing import List, Optional

from slr_agent.module2_screening_v2.models import ScreeningOutput, ScreeningConfig
from slr_agent.module2_screening_v2.layers import (
    EmbeddingService,
    PaperRanker,
    PromptBuilder,
    LLMClient,
)
from slr_agent.module2_screening.models import Paper, SearchQuery


def runScreeningV2(
    papers: List[Paper],
    query: SearchQuery,
    emitLog=None,
    config: Optional[ScreeningConfig] = None,
    runId: str = "",
    seedExamples: Optional[List[dict]] = None,
) -> ScreeningOutput:
    """Top-level entry point for v2 screening pipeline.

    This is a minimal skeleton wiring around Embedding -> Rank -> LLM-based
    screening. The L2/L3 stages currently placeholder for incremental development.
    """
    orchestrator = __import__(
        "slr_agent.module2_screening_v2", fromlist=["ScreeningOrchestrator"]
    ).ScreeningOrchestrator(
        config=config or ScreeningConfig(), seedExamples=seedExamples or []
    )  # type: ignore
    return orchestrator.run(papers, query, emitLog=emitLog)
