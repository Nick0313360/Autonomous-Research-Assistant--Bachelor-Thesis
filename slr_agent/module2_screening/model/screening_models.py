from dataclasses import dataclass
from typing import Literal, Dict, List, Optional
import numpy as np
from module1.model.Paper import Paper

@dataclass
class RankedPaper:
    """
    Module 2::Model::RankedPaper  (NEW — add to class diagram)

    Produced by PaperRanker (L1). Carries the original Paper, its embedding,
    and its cosine similarity score against the PICO query vector.

    Fields:
      paper      — original Paper from Module 1
      embedding  — np.ndarray (768,) float32; carried forward so L2/L3 can use
                   the embedding without re-computing it
      simScore   — float; cosine similarity to PICO embedding after L2-norm
                   higher = more semantically similar to the research question
      paperId    — str; unique identifier derived from doi or title hash;
                   used as dict key in DecisionAggregator

    Used by:
      L2 PrimaryScreener      — paper.title + paper.abstract for prompt
      L3 UncertaintyHandler   — embedding for ExampleBuffer.getSimilar()
      L4 DecisionAggregator   — paperId for decision merging
    """
    paper:     Paper
    embedding: np.ndarray
    simScore:  float
    paperId:   str

    def toDict(self) -> dict:
        """Serialise to dict for audit trail. Embedding omitted (too large)."""
        return {
            **self.paper.toDict(),
            "simScore": round(self.simScore, 6),
            "paperId":  self.paperId,
        }


@dataclass
class ScreeningResult:
    """
    Module 2::Model::ScreeningResult  (NEW — add to class diagram)
    REPLACES FirstPassResult from old architecture.

    Produced by PrimaryScreener (L2) for every retained paper.

    Fields:
      rankedPaper  — full RankedPaper (carries embedding for L3 buffer lookup)
      decision     — "INCLUDE" | "EXCLUDE" | "UNCERTAIN"
      confidence   — float 0-1; LLM self-assessed confidence
      rawResponse  — raw JSON string from LLM; stored for NFR-1 audit trail
      method       — always "llm_primary" for L2 output

    Decision mapping applied by PrimaryScreener:
      confidence >= 0.70 AND decision == INCLUDE  → INCLUDE
      confidence >= 0.70 AND decision == EXCLUDE  → EXCLUDE
      everything else                             → UNCERTAIN
      parse failure                               → UNCERTAIN / confidence=0.5

    Used by:
      L3 UncertaintyHandler  — filters where decision == "UNCERTAIN"
      L4 DecisionAggregator  — base decisions, overridden by L3 where available
    """
    rankedPaper: RankedPaper
    decision:    Literal["INCLUDE", "EXCLUDE", "UNCERTAIN"]
    confidence:  float
    rawResponse: str
    method:      str = "llm_primary"

    def toDict(self) -> dict:
        """Serialise for audit trail."""
        return {
            **self.rankedPaper.toDict(),
            "decision":    self.decision,
            "confidence":  round(self.confidence, 4),
            "method":      self.method,
        }


@dataclass
class ResolvedResult:
    """
    Module 2::Model::ResolvedResult  (NEW — add to class diagram)
    REPLACES ReevalResult from old architecture.

    Produced by UncertaintyHandler (L3) for every UNCERTAIN paper from L2.

    Fields:
      screeningResult  — original L2 ScreeningResult (full audit chain preserved)
      finalDecision    — "INCLUDE" | "EXCLUDE"
                         never UNCERTAIN; parse failures default to INCLUDE
      confidence       — float 0-1; LLM self-assessed
      reasoning        — full CoT reasoning text (satisfies FR-9)
      cotSteps         — dict of step-level reasoning extracted from JSON
                         {"step1_population": "...", "step2_intervention": "...",
                          "step3_outcome": "..."}
      examplesUsed     — int; how many ExampleBuffer entries were injected

    Used by:
      L4 DecisionAggregator — overrides L2 decision for the same paperId
    """
    screeningResult: ScreeningResult
    finalDecision:   Literal["INCLUDE", "EXCLUDE"]
    confidence:      float
    reasoning:       str
    cotSteps:        Dict[str, str]
    examplesUsed:    int

    def toDict(self) -> dict:
        """Serialise for audit trail."""
        return {
            **self.screeningResult.toDict(),
            "finalDecision": self.finalDecision,
            "confidence":    round(self.confidence, 4),
            "reasoning":     self.reasoning,
            "cotSteps":      self.cotSteps,
            "examplesUsed":  self.examplesUsed,
        }


@dataclass
class ScreeningOutput:
    """
    Module 2::Model::ScreeningOutput  (NEW — add to class diagram)
    REPLACES ScreeningResult from old architecture (old class renamed
    to avoid collision — the old ScreeningResult is now superseded by this).

    Returned by ScreeningOrchestrator.run(). Passed to Module 3.

    Fields:
      includedPapers  — List[Paper]; papers to send to full-text retrieval
      excludedPapers  — List[Paper]; papers excluded at T/A stage
      uncertainPapers — List[Paper]; papers that remained UNCERTAIN after L3
                        (treated as INCLUDE in L4 per recall-safe policy)
      allDecisions    — List[dict]; full audit trail, one entry per paper
                        merges L1 excluded_low_sim + L2 decisions + L3 overrides
      prismaSnapshot  — dict; PrismaLog.toDict() captured after L4 completes
    """
    includedPapers:  List[Paper]
    excludedPapers:  List[Paper]
    uncertainPapers: List[Paper]
    allDecisions:    List[dict]
    prismaSnapshot:  dict

    def toDict(self) -> dict:
        """Summary dict for pipeline handoff log."""
        return {
            "counts": {
                "included":  len(self.includedPapers),
                "excluded":  len(self.excludedPapers),
                "uncertain": len(self.uncertainPapers),
            },
            "prisma": self.prismaSnapshot,
        }


@dataclass
class ScreeningConfig:
    """
    Module 2::Model::ScreeningConfig  (NEW — add to class diagram)

    All tunable parameters for the screening pipeline in one place.
    Passed to ScreeningOrchestrator.__init__().

    Fields:
      similarityThreshold    — L1 cutoff; papers below this cosine sim are
                               immediately excluded; default 0.10 (very lenient)
      primaryConfidenceGate  — L2 confidence threshold; below this both
                               INCLUDE and EXCLUDE are escalated to UNCERTAIN;
                               default 0.70
      primaryConcurrency     — L2 semaphore size; default 20
      uncertaintyConcurrency — L3 semaphore size; default 5
      lowConfIncludeThresh   — L2 INCLUDE decisions below this confidence
                               are also sent to L3 for re-evaluation; default 0.85
      batchSize              — embedding batch size; default 32
      cacheDir               — if set, embeddings are cached to disk here
                               and reloaded on subsequent runs for the same papers
    """
    similarityThreshold:    float = 0.10
    primaryConfidenceGate:  float = 0.70
    primaryConcurrency:     int   = 20
    uncertaintyConcurrency: int   = 5
    lowConfIncludeThresh:   float = 0.85
    batchSize:              int   = 32
    cacheDir:               Optional[str] = None

