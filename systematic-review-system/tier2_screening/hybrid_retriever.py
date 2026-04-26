"""
tier2_screening/hybrid_retriever.py
=====================================
Hybrid BM25 + dense retrieval with Reciprocal Rank Fusion (RRF).

Pipeline
--------
1. build_indices()  — encode all abstracts, build faiss + BM25 indices
2. rank()           — score every candidate against a PICO query
3. filter()         — split into above / below threshold lists

RRF formula:  score(d) = 1/(60 + rank_bm25) + 1/(60 + rank_dense)
              (k=60 is the standard RRF constant)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from models.data_classes import CandidateRecord

logger = logging.getLogger(__name__)

_RRF_K = 60
_EMBED_BATCH = 32

# ---------------------------------------------------------------------------
# Tokeniser (NLTK punkt preferred; simple fallback if not downloaded)
# ---------------------------------------------------------------------------

def _make_tokeniser():
    try:
        import nltk
        nltk.data.find("tokenizers/punkt_tab")
        from nltk.tokenize import word_tokenize
        logger.debug("Using NLTK word_tokenize")
        return word_tokenize
    except Exception:
        try:
            import nltk
            nltk.download("punkt_tab", quiet=True)
            nltk.download("punkt", quiet=True)
            from nltk.tokenize import word_tokenize
            return word_tokenize
        except Exception:
            logger.warning("NLTK punkt unavailable — using regex tokeniser")
            return lambda text: re.findall(r"[a-z0-9]+", text.lower())

_tokenise = _make_tokeniser()


def _tokens(text: str) -> List[str]:
    return _tokenise(text.lower())


# ---------------------------------------------------------------------------
# RankedCandidate
# ---------------------------------------------------------------------------

@dataclass
class RankedCandidate:
    candidate:   CandidateRecord
    bm25_rank:   int      # 1 = best BM25 match
    dense_rank:  int      # 1 = best dense match
    rrf_score:   float    # higher = more relevant


# ---------------------------------------------------------------------------
# HybridRetriever
# ---------------------------------------------------------------------------

class HybridRetriever:
    """
    Hybrid retriever combining BM25 and dense (faiss) retrieval.

    Typical usage
    -------------
    retriever = HybridRetriever()
    retriever.build_indices(candidates, encoder)
    ranked = retriever.rank(candidates, pico_embedding, pico_query_text)
    above, below = retriever.filter(ranked)
    """

    def __init__(self) -> None:
        self._faiss_index:   Optional[faiss.IndexFlatIP] = None
        self._bm25:          Optional[BM25Okapi] = None
        self._id_map:        Dict[int, str] = {}   # faiss position → record_id
        self._record_map:    Dict[str, CandidateRecord] = {}   # record_id → record
        self._embed_dim:     int = 128

    # ------------------------------------------------------------------
    # build_indices
    # ------------------------------------------------------------------

    def build_indices(
        self,
        candidates: List[CandidateRecord],
        encoder,                          # SharedEncoderService
    ) -> None:
        """
        Encode all abstracts and build faiss + BM25 indices.

        Parameters
        ----------
        candidates : List[CandidateRecord]
        encoder :    SharedEncoderService — must have embed_abstract() and embed_batch()
        """
        if not candidates:
            logger.warning("build_indices: empty candidate list")
            return

        # ---- Encode abstracts (batched) -----------------------------------
        texts = [
            f"{r.title} [SEP] {(r.abstract or '')[:450]}"
            for r in candidates
        ]
        raw_vecs = encoder.embed_batch(texts, head_name="abstract", batch_size=_EMBED_BATCH)

        matrix = np.vstack(raw_vecs).astype(np.float32)
        # Vectors already L2-normalised by encoder; ensure it for safety
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms < 1e-12, 1.0, norms)
        matrix /= norms

        self._embed_dim = matrix.shape[1]

        # ---- Faiss (inner product on L2-normalised = cosine) --------------
        self._faiss_index = faiss.IndexFlatIP(self._embed_dim)
        self._faiss_index.add(matrix)

        # ---- BM25 ---------------------------------------------------------
        tokenised_docs = [
            _tokens((r.title or "") + " " + (r.abstract or ""))
            for r in candidates
        ]
        self._bm25 = BM25Okapi(tokenised_docs)

        # ---- Index maps ---------------------------------------------------
        self._id_map     = {i: r.record_id for i, r in enumerate(candidates)}
        self._record_map = {r.record_id: r for r in candidates}

        logger.info(
            "Built indices for %d candidates (dim=%d)",
            len(candidates),
            self._embed_dim,
        )

    # ------------------------------------------------------------------
    # rank
    # ------------------------------------------------------------------

    def rank(
        self,
        candidates:      List[CandidateRecord],
        pico_embedding:  np.ndarray,
        pico_query_text: str = "",
    ) -> List[RankedCandidate]:
        """
        Score all candidates and return them sorted by RRF score (desc).

        Parameters
        ----------
        candidates :       Same list passed to build_indices (used for ordering).
        pico_embedding :   L2-normalised 128-d vector from encoder.embed_pico().
        pico_query_text :  Space-joined PICO terms for BM25 scoring.
                           If empty, BM25 scores are all 0 and only dense ranking
                           contributes.
        """
        if self._faiss_index is None or self._bm25 is None:
            raise RuntimeError("Call build_indices() before rank()")

        n = len(candidates)
        id_order = [r.record_id for r in candidates]

        # ---- Dense ranking (faiss) ----------------------------------------
        q = pico_embedding.astype(np.float32).reshape(1, -1)
        norm = float(np.linalg.norm(q))
        if norm > 1e-12:
            q /= norm
        _, faiss_indices = self._faiss_index.search(q, n)
        faiss_order = faiss_indices[0]  # positions in faiss, best-first

        # position → dense rank (1-indexed)
        dense_rank_map: Dict[int, int] = {
            int(pos): rank + 1
            for rank, pos in enumerate(faiss_order)
        }

        # ---- BM25 ranking -------------------------------------------------
        if pico_query_text.strip():
            bm25_scores = self._bm25.get_scores(_tokens(pico_query_text))
        else:
            bm25_scores = np.zeros(n)

        # argsort descending (higher BM25 score = better = lower rank number)
        bm25_order = np.argsort(bm25_scores)[::-1]
        bm25_rank_map: Dict[int, int] = {
            int(pos): rank + 1
            for rank, pos in enumerate(bm25_order)
        }

        # ---- RRF fusion ---------------------------------------------------
        results: List[RankedCandidate] = []
        for i, rec in enumerate(candidates):
            dr = dense_rank_map.get(i, n)
            br = bm25_rank_map.get(i, n)
            rrf = 1.0 / (_RRF_K + br) + 1.0 / (_RRF_K + dr)
            results.append(
                RankedCandidate(
                    candidate  = rec,
                    bm25_rank  = br,
                    dense_rank = dr,
                    rrf_score  = rrf,
                )
            )

        results.sort(key=lambda x: x.rrf_score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # filter
    # ------------------------------------------------------------------

    def filter(
        self,
        ranked:    List[RankedCandidate],
        threshold: float = 0.01,
    ) -> Tuple[List[RankedCandidate], List[RankedCandidate]]:
        """
        Split ranked candidates at *threshold*.

        Default threshold of 0.01 is calibrated so that the top ~90 % of
        papers (by RRF score) pass through when there are ≥ 100 candidates.

        Returns
        -------
        (above_threshold, below_threshold)
        """
        above = [r for r in ranked if r.rrf_score >= threshold]
        below = [r for r in ranked if r.rrf_score <  threshold]
        logger.info(
            "filter(threshold=%.4f): %d above, %d below",
            threshold, len(above), len(below),
        )
        return above, below
