"""
tier2_screening/example_buffer.py
====================================
In-memory few-shot example store backed by a faiss index for
nearest-neighbour retrieval.

Seed examples are loaded from config/seed_examples.json at init.
High-confidence screening decisions (>= 0.90) can be appended at runtime.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import faiss
import numpy as np

logger = logging.getLogger(__name__)

_SEED_PATH       = Path(__file__).parent.parent / "config" / "seed_examples.json"
_CONFIDENCE_GATE = 0.90
_EMBED_DIM       = 128   # matches abstract_head output


@dataclass
class ScreeningExample:
    title:      str
    abstract:   str
    decision:   str          # "include" | "exclude" | "uncertain"
    reasoning:  str
    embedding:  Optional[np.ndarray] = field(default=None, repr=False)
    confidence: float = 0.0


class ExampleBuffer:
    """
    Few-shot example store.

    ``get_similar`` retrieves examples whose embeddings are closest (cosine)
    to a query embedding — useful for dynamic few-shot prompting.
    """

    def __init__(self, encoder=None) -> None:
        """
        Parameters
        ----------
        encoder : SharedEncoderService, optional
            If supplied, seed examples are encoded immediately.
            If None, embeddings are populated lazily on first add/query.
        """
        self._examples: List[ScreeningExample] = []
        self._index:    Optional[faiss.IndexFlatIP] = None
        self._encoder   = encoder

        self._load_seeds(encoder)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, example: ScreeningExample, encoder) -> None:
        """
        Add *example* if its confidence is >= 0.90.

        Rebuilds the faiss index after insertion.
        """
        if example.confidence < _CONFIDENCE_GATE:
            logger.debug(
                "ExampleBuffer.add: confidence %.2f < %.2f, skipping",
                example.confidence, _CONFIDENCE_GATE,
            )
            return

        if example.embedding is None:
            example.embedding = encoder.embed_abstract(example.title, example.abstract)

        self._examples.append(example)
        self._rebuild_index()
        logger.debug("ExampleBuffer: added example (total=%d)", len(self._examples))

    def get_similar(
        self,
        query_embedding: np.ndarray,
        n: int = 3,
    ) -> List[ScreeningExample]:
        """
        Return up to *n* examples nearest to *query_embedding* (cosine).
        """
        if self._index is None or not self._examples:
            return []

        k = min(n, len(self._examples))
        q = query_embedding.astype(np.float32).reshape(1, -1)
        norm = float(np.linalg.norm(q))
        if norm > 1e-12:
            q /= norm

        _, indices = self._index.search(q, k)
        return [self._examples[i] for i in indices[0] if i < len(self._examples)]

    def __len__(self) -> int:
        return len(self._examples)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_seeds(self, encoder) -> None:
        if not _SEED_PATH.exists():
            logger.warning("ExampleBuffer: seed file not found at %s", _SEED_PATH)
            return

        with _SEED_PATH.open(encoding="utf-8") as fh:
            seeds = json.load(fh)

        for raw in seeds:
            ex = ScreeningExample(
                title     = raw.get("title",    ""),
                abstract  = raw.get("abstract", ""),
                decision  = raw.get("decision", "uncertain"),
                reasoning = raw.get("reasoning", ""),
                confidence= float(raw.get("confidence", 1.0)),
            )
            if encoder is not None:
                ex.embedding = encoder.embed_abstract(ex.title, ex.abstract)
            self._examples.append(ex)

        if encoder is not None:
            self._rebuild_index()

        logger.info(
            "ExampleBuffer: loaded %d seed examples from %s",
            len(self._examples), _SEED_PATH,
        )

    def _rebuild_index(self) -> None:
        """Rebuild faiss IndexFlatIP from all stored embeddings."""
        embedded = [e for e in self._examples if e.embedding is not None]
        if not embedded:
            return

        dim = embedded[0].embedding.shape[0]
        matrix = np.vstack([e.embedding for e in embedded]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms < 1e-12, 1.0, norms)
        matrix /= norms

        self._index = faiss.IndexFlatIP(dim)
        self._index.add(matrix)
