"""Module 2 Screening v2 (branch: feature2_screening_l)

New architecture: L0 -> L4 with EmbeddingService, PaperRanker,
PrimaryScreener, UncertaintyHandler, DecisionAggregator.
"""

from .models import (
    RankedPaper,
    ScreeningResult,
    ResolvedResult,
    ScreeningOutput,
    ScreeningConfig,
)

from .layers import (
    EmbeddingService,
    PaperRanker,
    PrimaryScreener,
    UncertaintyHandler,
    PromptBuilder,
    LLMClient,
    ScreeningOrchestrator,
)

__all__ = [
    "RankedPaper",
    "ScreeningResult",
    "ResolvedResult",
    "ScreeningOutput",
    "ScreeningConfig",
    "EmbeddingService",
    "PaperRanker",
    "PrimaryScreener",
    "UncertaintyHandler",
    "PromptBuilder",
    "LLMClient",
    "ScreeningOrchestrator",
]
