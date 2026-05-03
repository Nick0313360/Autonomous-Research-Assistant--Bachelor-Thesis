"""Module 2 — Layers (L1-L5)"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

import numpy as np
from transformers import AutoModel, AutoTokenizer
import torch

from .models import (
    Paper,
    SearchQuery,
    EmbeddedPaper,
)

log = logging.getLogger(__name__)


def _log(emitLog: Optional[callable], message: str, count: int = 0) -> None:
    if emitLog:
        try:
            emitLog("screen", message, count)
        except TypeError:
            emitLog("screen", message)


# ══════════════════════════════════════════════════════════════════════════════
# L1: EMBEDDING LAYER
# ══════════════════════════════════════════════════════════════════════════════


class EmbeddingLayer:
    """
    Module 2::Layer::EmbeddingLayer
    DATA IN:  papers (List[Paper]), query (SearchQuery)
    DATA OUT: List[EmbeddedPaper], picoEmbedding (768,)
    """

    MODELS = {
        "specter2": "allenai/specter2_base",
        "medcpt": "ncats/MedCPT-Article-Encoder",
    }
    SPECTER2_FINETUNED_PATH = "./specter2_screening"
    BIO_SIGNALS = frozenset(
        {
            "health",
            "clinical",
            "patient",
            "medical",
            "disease",
            "treatment",
            "trial",
            "drug",
            "therapy",
            "hospital",
            "pharma",
            "epidemiology",
            "randomized",
        }
    )

    def __init__(self, modelKey: Optional[str] = None, device: str = "auto"):
        self._modelKey = modelKey
        self._device = (
            "cuda" if (device == "auto" and torch.cuda.is_available()) else "cpu"
        )
        self._tokenizer: Optional[AutoTokenizer] = None
        self._model: Optional[AutoModel] = None
        self._loadedKey: str = ""

    def selectModel(self, query: SearchQuery) -> str:
        if self._modelKey:
            return self._modelKey
        text = (query.population + " " + query.intervention).lower()
        return "medcpt" if any(s in text for s in self.BIO_SIGNALS) else "specter2"

    def embedPapers(
        self,
        papers: List[Paper],
        modelKey: str,
        batchSize: int = 32,
    ) -> List[EmbeddedPaper]:
        self._loadModel(modelKey)
        results: List[EmbeddedPaper] = []
        for i in range(0, len(papers), batchSize):
            batch = papers[i : i + batchSize]
            vecs = self._encodeBatch(
                [p.title for p in batch],
                [p.abstract for p in batch],
            )
            for paper, vec in zip(batch, vecs):
                results.append(
                    EmbeddedPaper(
                        paper=paper,
                        embedding=vec.astype(np.float32),
                        modelId=modelKey,
                    )
                )
        return results

    def embedQuery(self, query: SearchQuery, modelKey: str) -> np.ndarray:
        self._loadModel(modelKey)
        doc = self._buildPicoDocument(query)
        return self._encodeBatch([doc], [""])[0].astype(np.float32)

    def _buildPicoDocument(self, query: SearchQuery) -> str:
        parts = [
            query.researchQuestion,
            f"Population: {query.population}",
            f"Intervention: {query.intervention}",
            f"Outcome: {query.outcome}",
        ]
        if query.comparison:
            parts.append(f"Comparison: {query.comparison}")
        return " ".join(p for p in parts if p.strip())

    def _loadModel(self, modelKey: str) -> None:
        if self._loadedKey == modelKey:
            return
        if modelKey == "specter2" and os.path.isdir(self.SPECTER2_FINETUNED_PATH):
            modelPath = self.SPECTER2_FINETUNED_PATH
            log.info("EmbeddingLayer: using fine-tuned SPECTER2 from %s", modelPath)
        else:
            modelPath = self.MODELS[modelKey]
            log.info("EmbeddingLayer: loading base model %s", modelPath)
        self._tokenizer = AutoTokenizer.from_pretrained(modelPath)
        self._model = AutoModel.from_pretrained(modelPath).to(self._device)
        self._model.eval()
        self._loadedKey = modelKey

    def _encodeBatch(self, titles: List[str], abstracts: List[str]) -> np.ndarray:
        texts = [f"{t} [SEP] {a[:400]}" for t, a in zip(titles, abstracts)]
        enc = self._tokenizer(
            texts,
            truncation=True,
            padding=True,
            max_length=512,
            return_tensors="pt",
        ).to(self._device)
        with torch.no_grad():
            out = self._model(**enc)
        return out.last_hidden_state[:, 0, :].cpu().numpy()
