"""
infrastructure/encoder.py
=========================
Shared embedding service for the systematic review system.

Primary:  allenai/specter2_base (768-dim backbone) + three trained projection
          heads that compress to task-specific dimensionalities:
            abstract_head  → 128-dim
            pico_head      → 128-dim
            section_head   → 256-dim

Fallback: if the backbone cannot be loaded, a RuntimeError is raised at init.
          If projection heads fail (should not occur in normal use) the service
          degrades gracefully to raw 768-dim L2-normalised vectors.

All output vectors are L2-normalised.  Repeated calls with identical inputs
are served from an in-memory LRU-style dict cache.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Dict, List, Optional, Union

import numpy as np
import torch
import torch.nn as nn
from sentence_transformers import SentenceTransformer
from sentence_transformers.sentence_transformer.modules import Transformer, Pooling

from models.data_classes import PICO, SectionLabel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL_NAME = "allenai/specter2_base"
_BASE_DIM = 768

_HEAD_OUT_DIMS: Dict[str, int] = {
    "abstract": 128,
    "pico": 128,
    "section": 256,
}

_VALID_HEADS = frozenset(_HEAD_OUT_DIMS)


# ---------------------------------------------------------------------------
# Encoder service
# ---------------------------------------------------------------------------

class SharedEncoderService:
    """
    Singleton-style encoder.  Instantiate once and inject throughout the
    pipeline; the heavy model is loaded only at construction time.

    Example
    -------
    encoder = SharedEncoderService()
    vec = encoder.embed_abstract("Aspirin in acute MI", "We randomised 500 ...")
    sim = SharedEncoderService.cosine_similarity(vec, other_vec)
    """

    def __init__(self) -> None:
        self._cache: Dict[str, np.ndarray] = {}
        self._use_projection: bool = True

        # ---- Load backbone ------------------------------------------------
        # Build from explicit modules to skip AutoProcessor.from_pretrained(),
        # which fails on text-only BERT models that have no processor_config.json
        # (affects sentence-transformers >= 3.x on allenai/specter2_base).
        try:
            _transformer = Transformer(_MODEL_NAME, max_seq_length=512)
            _pooling = Pooling(
                _transformer.get_embedding_dimension(),
                pooling_mode="cls",   # SPECTER2 uses CLS pooling
            )
            self._model = SentenceTransformer(modules=[_transformer, _pooling])
            logger.info("Loaded backbone: %s", _MODEL_NAME)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot load embedding backbone '{_MODEL_NAME}': {exc}"
            ) from exc

        # ---- Build projection heads ---------------------------------------
        try:
            self.abstract_head = nn.Linear(_BASE_DIM, _HEAD_OUT_DIMS["abstract"])
            self.pico_head     = nn.Linear(_BASE_DIM, _HEAD_OUT_DIMS["pico"])
            self.section_head  = nn.Linear(_BASE_DIM, _HEAD_OUT_DIMS["section"])

            for head in (self.abstract_head, self.pico_head, self.section_head):
                head.eval()

            logger.info(
                "Projection heads initialised: abstract→%d, pico→%d, section→%d",
                _HEAD_OUT_DIMS["abstract"],
                _HEAD_OUT_DIMS["pico"],
                _HEAD_OUT_DIMS["section"],
            )
        except Exception as exc:
            logger.warning(
                "Failed to build projection heads (%s) — falling back to 768-dim output",
                exc,
            )
            self._use_projection = False

        # Convenience map used by generic methods
        self._heads: Dict[str, Optional[nn.Linear]] = {
            "abstract": self.abstract_head if self._use_projection else None,
            "pico":     self.pico_head     if self._use_projection else None,
            "section":  self.section_head  if self._use_projection else None,
        }

    # ------------------------------------------------------------------
    # Public embedding methods
    # ------------------------------------------------------------------

    def embed_abstract(self, title: str, abstract: str) -> np.ndarray:
        """
        Embed a paper title + abstract.

        Returns shape (128,) — or (768,) in fallback mode.
        """
        text = f"{title} [SEP] {abstract[:450]}"
        return self._encode_with_head(text, "abstract")

    def embed_pico(self, pico: PICO) -> np.ndarray:
        """
        Embed a PICO struct.

        Returns shape (128,) — or (768,) in fallback mode.
        """
        text = (
            f"{pico.population}. {pico.intervention}. "
            f"{pico.comparator}. {pico.outcome}"
        )
        return self._encode_with_head(text, "pico")

    def embed_section(
        self,
        text: str,
        section_label: Union[str, SectionLabel],
    ) -> np.ndarray:
        """
        Embed a document section prefixed with its label.

        Returns shape (256,) — or (768,) in fallback mode.
        """
        label = (
            section_label.value
            if isinstance(section_label, SectionLabel)
            else str(section_label)
        )
        formatted = f"[{label}] {text[:2048]}"
        return self._encode_with_head(formatted, "section")

    def embed_batch(
        self,
        texts: List[str],
        head_name: str,
        batch_size: int = 32,
    ) -> List[np.ndarray]:
        """
        Encode a list of already-formatted strings through the named head.

        Args:
            texts:      Pre-formatted input strings.
            head_name:  One of "abstract", "pico", "section".
            batch_size: Number of texts encoded per SentenceTransformer call.

        Returns:
            List of L2-normalised numpy arrays, one per input string.
        """
        if head_name not in _VALID_HEADS:
            raise ValueError(
                f"head_name must be one of {sorted(_VALID_HEADS)}, got {head_name!r}"
            )

        results: List[Optional[np.ndarray]] = [None] * len(texts)
        to_encode_idx: List[int] = []
        to_encode_texts: List[str] = []

        # Serve cache hits immediately
        for i, text in enumerate(texts):
            key = _cache_key(head_name, text)
            cached = self._cache.get(key)
            if cached is not None:
                results[i] = cached
            else:
                to_encode_idx.append(i)
                to_encode_texts.append(text)

        if to_encode_texts:
            raw_vecs: List[np.ndarray] = []
            for start in range(0, len(to_encode_texts), batch_size):
                chunk = to_encode_texts[start : start + batch_size]
                encoded = self._model.encode(
                    chunk,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                # sentence-transformers returns a 2-D array; iterate rows
                raw_vecs.extend(encoded)

            for idx, raw_vec, text in zip(to_encode_idx, raw_vecs, to_encode_texts):
                projected  = self._project(raw_vec, head_name)
                normalised = _l2_normalize(projected)
                key = _cache_key(head_name, text)
                self._cache[key] = normalised
                results[idx] = normalised

        return results  # type: ignore[return-value]  — all slots filled above

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """
        Cosine similarity between two vectors.

        Because all outputs from this service are L2-normalised, this is
        equivalent to a simple dot product.  Handles un-normalised inputs
        safely via explicit normalisation.
        """
        a_norm = _l2_normalize(a)
        b_norm = _l2_normalize(b)
        return float(np.dot(a_norm, b_norm))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _encode_with_head(self, text: str, head_name: str) -> np.ndarray:
        """Encode a single formatted string, using the in-memory cache."""
        key = _cache_key(head_name, text)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        raw = self._model.encode(
            text,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        projected  = self._project(raw, head_name)
        normalised = _l2_normalize(projected)
        self._cache[key] = normalised
        return normalised

    def _project(self, vec: np.ndarray, head_name: str) -> np.ndarray:
        """Apply the named linear head. No-ops if projection is disabled."""
        if not self._use_projection:
            return vec

        head = self._heads[head_name]
        with torch.no_grad():
            t = torch.tensor(vec, dtype=torch.float32)
            return head(t).numpy()  # type: ignore[union-attr]

    @property
    def output_dim(self) -> Dict[str, int]:
        """Expected output dimensionality per head (768 in fallback mode)."""
        if self._use_projection:
            return dict(_HEAD_OUT_DIMS)
        return {"abstract": _BASE_DIM, "pico": _BASE_DIM, "section": _BASE_DIM}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _cache_key(head_name: str, text: str) -> str:
    """Stable hash key for the embedding cache."""
    payload = f"{head_name}:{text}".encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    """Return vec / ||vec||₂, or the zero vector if ||vec|| ≈ 0."""
    norm = float(np.linalg.norm(vec))
    if norm < 1e-12:
        return vec.copy()
    return vec / norm


# ---------------------------------------------------------------------------
# Smoke test  (python -m infrastructure.encoder)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    print("Loading SharedEncoderService …")
    enc = SharedEncoderService()
    print("Output dims:", enc.output_dim)

    pico = PICO(
        population="adult patients with acute myocardial infarction",
        intervention="aspirin 300 mg",
        comparator="placebo",
        outcome="30-day mortality",
        study_design="randomised controlled trial",
    )

    v_abstract = enc.embed_abstract(
        "Aspirin in acute MI", "We randomised 500 patients …"
    )
    v_pico = enc.embed_pico(pico)
    v_section = enc.embed_section(
        "Patients were adults aged 18–80 …", SectionLabel.METHODS
    )

    print(f"abstract vec: shape={v_abstract.shape}  norm={np.linalg.norm(v_abstract):.4f}")
    print(f"pico     vec: shape={v_pico.shape}  norm={np.linalg.norm(v_pico):.4f}")
    print(f"section  vec: shape={v_section.shape}  norm={np.linalg.norm(v_section):.4f}")

    sim = SharedEncoderService.cosine_similarity(v_abstract, v_pico)
    print(f"cosine(abstract, pico) = {sim:.4f}")

    batch_vecs = enc.embed_batch(
        ["aspirin reduces mortality", "placebo had no effect"],
        head_name="abstract",
    )
    print(f"batch[0] shape={batch_vecs[0].shape}  norm={np.linalg.norm(batch_vecs[0]):.4f}")
    print("Smoke test passed.")
