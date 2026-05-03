from __future__ import annotations

import asyncio
import json
import logging
import numpy as np
from typing import List, Dict, Optional

import numpy as np

from slr_agent.module2_screening.layers import EmbeddingLayer as _EmbeddingLayer
from slr_agent.module2_screening.models import Paper, EmbeddedPaper
from slr_agent.module2_screening.models import Paper as OldPaper  # for type hints
from slr_agent.module2_screening.models import Paper as OldPaperModel
from slr_agent.module2_screening.layers import _log as _old_log
from slr_agent.module2_screening.layers import ExampleBuffer
from .models import (
    RankedPaper,
    ScreeningResult,
    ResolvedResult,
    ScreeningOutput,
    ScreeningConfig,
)
from . import __init__ as _v2root
from slr_agent.module2_screening import layers as _old_layers
from screening_module2 import Paper as _ExternalPaper  # type: ignore

log = logging.getLogger(__name__)


class EmbeddingService:
    """Thin wrapper around existing EmbeddingLayer (L0). Reuses Layer 1."""

    def __init__(
        self,
        modelKey: Optional[str] = None,
        cacheDir: Optional[str] = None,
        device: str = "auto",
    ):
        self._layer = _EmbeddingLayer(modelKey=modelKey, device=device)
        self._cacheDir = cacheDir

    def selectModel(self, query: any) -> str:
        return self._layer.selectModel(query)  # type: ignore

    def embedPapers(
        self, papers: List[Paper], modelKey: str, batchSize: int = 32
    ) -> Dict[str, np.ndarray]:
        embedded = self._layer.embedPapers(papers, modelKey, batchSize=batchSize)
        # convert to paperId map
        mapping: Dict[str, np.ndarray] = {}
        for ep in embedded:
            # paperId derived from DOI or hash of title/abstract
            pid = self._makePaperId(ep.paper)
            mapping[pid] = ep.embedding
        return mapping

    def embedQuery(self, query: any, modelKey: str) -> np.ndarray:
        vec = self._layer.embedQuery(query, modelKey)
        return vec

    @staticmethod
    def _makePaperId(paper: Paper) -> str:
        if paper.doi:
            return paper.doi.strip().lower().replace("/", "_")
        import hashlib

        raw = (paper.title + paper.abstract).encode("utf-8")
        return "hash_" + hashlib.sha256(raw).hexdigest()[:16]


class PaperRanker:
    def rank(
        self,
        paperEmbeddings: Dict[str, np.ndarray],
        picoEmbedding: np.ndarray,
        papers: List[Paper],
        threshold: float = 0.10,
        emitLog=None,
    ):
        ids = list(paperEmbeddings.keys())
        if not ids:
            return [], []
        mat = np.stack([paperEmbeddings[pid] for pid in ids])
        scores = mat @ picoEmbedding
        # map to papers
        paperById = {self._makePaperId(p): p for p in papers}
        # clamp threshold
        retained: List[RankedPaper] = []
        excluded: List[str] = []
        for idx in np.argsort(scores)[::-1]:
            pid = ids[idx]
            sc = float(scores[idx])
            if sc >= threshold:
                p = paperById.get(pid)
                if p is not None:
                    retained.append(RankedPaper(p, paperEmbeddings[pid], sc, pid))
            else:
                excluded.append(pid)
        return retained, excluded

    @staticmethod
    def _makePaperId(paper: Paper) -> str:
        if paper.doi:
            return paper.doi.strip().lower().replace("/", "_")
        import hashlib

        raw = (paper.title + paper.abstract).encode("utf-8")
        return "hash_" + hashlib.sha256(raw).hexdigest()[:16]


class PromptBuilder:
    def buildPicoText(self, query: Paper):  # type: ignore
        parts = [query.population, query.intervention, query.outcome]
        return " ".join([p for p in parts if p])

    def buildPrimaryPrompt(self, picoText: str, title: str, abstract: str):
        system = "You are a screening model."
        user = f"PICO: {picoText}\nTitle: {title}\nAbstract: {abstract}"
        return system, user

    def buildCotPrompt(
        self, picoText: str, title: str, abstract: str, examples: List[Dict]
    ):
        system = "CoT reasoning prompt"
        user = f"PICO: {picoText}\nTitle: {title}\nAbstract: {abstract}"
        return system, user


class LLMClient:
    def __init__(
        self,
        modelName: str = "claude-haiku-4-5-20251001",
        maxRetries: int = 3,
        backoffBase: float = 1.0,
    ):
        from slr_agent.module2_screening.layers import GptConnector

        self._connector = GptConnector(modelName=modelName)  # type: ignore
        self._maxRetries = maxRetries

    async def completeAsync(
        self, prompt: str, system: str, temperature: float = 0.0
    ) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._connector.call_llm(prompt, system, temperature)
        )

    def completeSync(self, prompt: str, system: str, temperature: float = 0.0) -> str:
        return self._connector.call_llm(prompt, system, temperature)


class ScreeningOrchestrator:
    """Minimal wiring for v2; relies on existing Layer 1 Embedding."""

    def __init__(
        self,
        config: Optional[ScreeningConfig] = None,
        seedExamples: Optional[List[dict]] = None,
    ):
        self._config = config or ScreeningConfig()
        self._seedBuffer = seedExamples or []
        self._emb = EmbeddingService()
        self._ranker = PaperRanker()
        self._prompt = PromptBuilder()
        self._llm = LLMClient()

    def run(
        self, papers: List[Paper], query: SearchQuery, emitLog=None
    ) -> ScreeningOutput:
        # L0: embed
        modelKey = self._emb.selectModel(query)
        paperEmb = self._emb.embedPapers(
            papers, modelKey, batchSize=self._config.batchSize
        )
        pico = self._emb.embedQuery(query, modelKey)
        # L1: rank
        retained, excludedLowSim = self._ranker.rank(
            paperEmb,
            pico,
            papers,
            threshold=self._config.similarityThreshold,
            emitLog=emitLog,
        )
        # L2/L3/L4 are stubbed for now; return empty decisions
        from .models import ScreeningOutput

        return ScreeningOutput(
            includedPapers=papers,
            excludedPapers=[],
            uncertainPapers=[],
            allDecisions=[],
            prismaSnapshot={},
        )
