from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
from sklearn.preprocessing import normalize
import logging
import torch
from transformers import AutoModel, AutoTokenizer
from module1.model.SearchQuery import SearchQuery
from mode
log = logging.getLogger(__name__)

class EmbeddingLayer:
    """
    Module 2::Layer::EmbeddingLayer

    IMPLEMENTATION ORDER:
      1. _loadModel()         — lazy load transformer + tokenizer from disk
      2. _encodeBatch()       — tokenize → forward → CLS pool → (N,768) numpy
      3. _buildPicoDocument() — concatenate PICO fields into one pseudo-document
      4. embedPapers()        — batch loop List[Paper] → List[EmbeddedPaper]
      5. embedQuery()         — embed PICO pseudo-document → (768,) anchor vector
      6. selectModel()        — heuristic: biomedical → MedCPT, else SPECTER2

    DATA INTO _encodeBatch():
      titles:    List[str]  — one per paper in batch
      abstracts: List[str]  — truncated to 400 chars before concatenation
      format:    "{title} [SEP] {abstract[:400]}" per item
      tokenized: max_length=512, padded, truncated

    DATA OUT of _encodeBatch():
      np.ndarray shape (batch_size, 768) float32
      out.last_hidden_state[:, 0, :] — CLS token only (index 0 of sequence)

    DATA INTO embedQuery():
      SearchQuery — all PICO fields joined:
      "{researchQuestion} Population: {population} Intervention: {intervention}
       Outcome: {outcome} [Comparison: {comparison}]"

    DATA OUT of embedQuery():
      np.ndarray shape (768,) float32
      → picoEmbedding; positive-class anchor for L2 and L3a
    """

    MODELS = {
        "specter2": "allenai/specter2_base",
        "medcpt":   "ncats/MedCPT-Article-Encoder",
    }
    SPECTER2_FINETUNED_PATH = "./specter2_screening"
    BIO_SIGNALS = frozenset({
        "health", "clinical", "patient", "medical", "disease",
        "treatment", "trial", "drug", "therapy", "hospital",
        "pharma", "epidemiology", "randomized",
    })

    def __init__(self, modelKey: Optional[str] = None, device: str = "auto"):
        self._modelKey  = modelKey
        self._device    = "cuda" if (device == "auto" and torch.cuda.is_available()) else "cpu"
        self._tokenizer: Optional[AutoTokenizer] = None
        self._model:     Optional[AutoModel]     = None
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
            batch = papers[i: i + batchSize]
            vecs  = self._encodeBatch(
                [p.title    for p in batch],
                [p.abstract for p in batch],
            )
            for paper, vec in zip(batch, vecs):
                results.append(EmbeddedPaper(
                    paper=paper,
                    embedding=vec.astype(np.float32),
                    modelId=modelKey,
                ))
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
        self._model     = AutoModel.from_pretrained(modelPath).to(self._device)
        self._model.eval()
        self._loadedKey = modelKey

    def _encodeBatch(self, titles: List[str], abstracts: List[str]) -> np.ndarray:
        texts = [f"{t} [SEP] {a[:400]}" for t, a in zip(titles, abstracts)]
        enc   = self._tokenizer(
            texts,
            truncation=True,
            padding=True,
            max_length=512,
            return_tensors="pt",
        ).to(self._device)
        with torch.no_grad():
            out = self._model(**enc)
        return out.last_hidden_state[:, 0, :].cpu().numpy()