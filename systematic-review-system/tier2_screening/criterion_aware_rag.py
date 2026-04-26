"""
tier2_screening/criterion_aware_rag.py
========================================
Criterion-level retrieve-then-read for long full-text documents.

For each criterion:
  1. Sentence-tokenise the full document and build per-document FAISS +
     BM25 indices (built once, reused across criteria).
  2. Query both indices with the criterion text; union top-5 hits from each.
  3. Cap the retrieved context at ~1 500 tokens, fill the LLM prompt.
  4. Verify the returned evidence span; apply hallucination penalty.

This module is called by FullTextScreener._tier3_screen() for documents
with more than 12 000 tokens.

Public interface matches what fulltext_screener.py expects:
    rag = CriterionAwareRAG()
    cr  = await rag.screen_criterion(criterion, document, abstract_context,
                                     protocol, encoder, llm_client, verifier)
``check()`` is provided as a convenience alias without the ``protocol`` arg.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from models.data_classes import (
    AbstractContext,
    CriterionResult,
    CriterionType,
    Decision,
    ReviewProtocol,
    ScreeningTier,
    SectionLabel,
    StructuredDocument,
)

try:
    import nltk
    nltk.data.find("tokenizers/punkt_tab")
    from nltk.tokenize import sent_tokenize as _sent_tokenize
except Exception:
    try:
        import nltk
        nltk.download("punkt_tab", quiet=True)
        nltk.download("punkt", quiet=True)
        from nltk.tokenize import sent_tokenize as _sent_tokenize
    except Exception:
        # Bare-minimum fallback: split on ". "
        def _sent_tokenize(text: str) -> List[str]:  # type: ignore[misc]
            return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

logger = logging.getLogger(__name__)

_PROMPT_PATH      = Path(__file__).parent.parent / "config" / "prompts" / "criterion_check.txt"
_TOP_K            = 5         # sentences per retriever
_TOKEN_BUDGET     = 1_500     # approximate token cap on retrieved context
_HALLUCINATION_MUL = 0.30
_FALSE_CAP         = 0.30
_INCLUDE_THRESH    = 0.70
_EXCLUDE_THRESH    = 0.25

# BM25 stop-words (minimal set for keyword extraction)
_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would could should may might shall must can its it the of in "
    "on at to for with by from and or not but if this that which who "
    "as such any all some than more most less very also".split()
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_template() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "You are a precise systematic review screener.\n\n"
        "PICO:\n{pico_text}\n\n"
        "Criterion:\n{criterion_text}\n\n"
        "Context:\n{context_text}\n\n"
        'Reply with JSON only: {"satisfies": true|false, "confidence": <0.0-1.0>, '
        '"evidence_span": "<verbatim quote or empty string>", "reasoning": "<one sentence>"}'
    )


_TEMPLATE = _load_template()


def _fill_template(template: str, **kwargs: str) -> str:
    """Safely substitute named placeholders without interpreting other braces."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def _format_pico(protocol: Optional[ReviewProtocol]) -> str:
    if protocol is None:
        return "PICO: not provided"
    p = protocol.pico
    return (
        f"Population: {p.population}\n"
        f"Intervention: {p.intervention}\n"
        f"Comparator: {p.comparator}\n"
        f"Outcome: {p.outcome}\n"
        f"Study design: {p.study_design}"
    )


def _tokenise_bm25(text: str) -> List[str]:
    return [
        t for t in re.findall(r"[a-z0-9]+", text.lower())
        if len(t) >= 3 and t not in _STOP_WORDS
    ]


def _criterion_keywords(text: str) -> List[str]:
    """Return keyword tokens extracted from a criterion string."""
    return _tokenise_bm25(text)


def _approx_tokens(text: str) -> int:
    return max(1, int(len(text.split()) / 0.75))


def _decide(p: float) -> Decision:
    if p >= _INCLUDE_THRESH:
        return Decision.INCLUDE
    if p <= _EXCLUDE_THRESH:
        return Decision.EXCLUDE
    return Decision.UNCERTAIN


def _normalise_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms < 1e-12, 1.0, norms)
    return matrix / norms


# ---------------------------------------------------------------------------
# DocumentIndex: built once per document, reused across criteria
# ---------------------------------------------------------------------------

class _DocumentIndex:
    """
    FAISS + BM25 index over all sentences in a StructuredDocument.
    """

    def __init__(
        self,
        sentences:     List[str],
        embeddings:    np.ndarray,   # (n_sentences, embed_dim) L2-normalised
        bm25:          BM25Okapi,
    ) -> None:
        self.sentences  = sentences
        self._bm25      = bm25
        dim             = embeddings.shape[1]
        self._faiss     = faiss.IndexFlatIP(dim)
        self._faiss.add(embeddings)

    @classmethod
    def build(
        cls,
        document: StructuredDocument,
        encoder,
    ) -> "_DocumentIndex":
        """Tokenise document into sentences and build both indices."""
        # Collect text from all sections
        all_text = "\n\n".join(document.sections.values())

        # Sentence tokenise
        raw_sentences = _sent_tokenize(all_text)
        sentences = [s.strip() for s in raw_sentences if len(s.strip()) > 10]

        if not sentences:
            sentences = [all_text[:500]] if all_text.strip() else ["<empty>"]

        # Embed using the section head
        formatted = [f"[other] {s[:512]}" for s in sentences]
        raw_embs  = encoder.embed_batch(formatted, head_name="section", batch_size=32)
        matrix    = np.vstack(raw_embs).astype(np.float32)
        matrix    = _normalise_rows(matrix)

        # BM25
        tokenised = [_tokenise_bm25(s) for s in sentences]
        bm25      = BM25Okapi(tokenised)

        logger.debug(
            "DocumentIndex: %d sentences indexed for %s",
            len(sentences), document.record_id,
        )
        return cls(sentences, matrix, bm25)

    def retrieve(
        self,
        criterion_emb: np.ndarray,   # (embed_dim,) L2-normalised
        keywords:      List[str],
        top_k:         int = _TOP_K,
    ) -> List[Tuple[int, float]]:
        """
        Return up to 2*top_k (sentence_index, score) pairs, deduped.
        Combines dense and BM25 results.
        """
        n = len(self.sentences)
        k = min(top_k, n)

        # Dense (faiss)
        q = criterion_emb.astype(np.float32).reshape(1, -1)
        norm = float(np.linalg.norm(q))
        if norm > 1e-12:
            q = q / norm
        _, faiss_idx = self._faiss.search(q, k)
        dense_hits   = set(int(i) for i in faiss_idx[0] if 0 <= i < n)

        # BM25
        if keywords:
            bm25_scores = self._bm25.get_scores(keywords)
            bm25_order  = np.argsort(bm25_scores)[::-1][:k]
            bm25_hits   = set(int(i) for i in bm25_order if bm25_scores[i] > 0)
        else:
            bm25_hits = set()

        # Union → scored by dense similarity
        combined_idx = list(dense_hits | bm25_hits)
        if not combined_idx:
            combined_idx = list(range(min(k, n)))

        q_flat = q.flatten()
        scored = [
            (i, float(self._faiss.reconstruct(i).dot(q_flat)))
            for i in combined_idx
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


# ---------------------------------------------------------------------------
# CriterionAwareRAG
# ---------------------------------------------------------------------------

class CriterionAwareRAG:
    """
    Retrieve-then-read screener for individual eligibility criteria.

    Builds a per-document index on the first call and caches it for
    subsequent criteria evaluated against the same document.
    """

    def __init__(self) -> None:
        # Cache: document.record_id → _DocumentIndex
        self._index_cache: Dict[str, _DocumentIndex] = {}

    # ------------------------------------------------------------------
    # Primary interface (matches fulltext_screener.py expectations)
    # ------------------------------------------------------------------

    async def screen_criterion(
        self,
        criterion:        Any,                         # models.data_classes.Criterion
        document:         StructuredDocument,
        abstract_context: Optional[AbstractContext],
        protocol:         Optional[ReviewProtocol],
        encoder:          Any,                         # SharedEncoderService
        llm_client:       Any,                         # LLMClient
        verifier:         Any,                         # SpanVerifier
    ) -> CriterionResult:
        """
        Screen a single criterion against a full-text document using RAG.
        """
        try:
            return await self._do_screen(
                criterion, document, abstract_context, protocol,
                encoder, llm_client, verifier,
            )
        except Exception as exc:
            logger.warning(
                "CriterionAwareRAG: failed for %s / %s: %s",
                document.record_id, criterion.criterion_id, exc,
            )
            p_prior = (
                (abstract_context.criterion_probabilities.get(criterion.criterion_id, 0.5)
                 if abstract_context else 0.5)
            )
            return CriterionResult(
                criterion_id = criterion.criterion_id,
                p_satisfy    = p_prior,
                decision     = _decide(p_prior),
            )

    async def check(
        self,
        criterion:        Any,
        document:         StructuredDocument,
        abstract_context: Optional[AbstractContext],
        encoder:          Any,
        llm_client:       Any,
        verifier:         Any,
    ) -> CriterionResult:
        """Convenience alias without the ``protocol`` argument."""
        return await self.screen_criterion(
            criterion        = criterion,
            document         = document,
            abstract_context = abstract_context,
            protocol         = None,
            encoder          = encoder,
            llm_client       = llm_client,
            verifier         = verifier,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _do_screen(
        self,
        criterion:        Any,
        document:         StructuredDocument,
        abstract_context: Optional[AbstractContext],
        protocol:         Optional[ReviewProtocol],
        encoder:          Any,
        llm_client:       Any,
        verifier:         Any,
    ) -> CriterionResult:
        # Step 1 & 2: Build / retrieve per-document index
        doc_index = self._get_or_build_index(document, encoder)

        # Step 3 & 4: Retrieve relevant sentences
        criterion_emb = encoder.embed_section(
            criterion.text, SectionLabel.OTHER
        ).astype(np.float32)
        keywords = _criterion_keywords(criterion.text)

        hits    = doc_index.retrieve(criterion_emb, keywords, top_k=_TOP_K)
        context = self._build_context(doc_index.sentences, hits)

        # Step 5: LLM call
        pico_text = _format_pico(protocol)
        prompt = _fill_template(
            _TEMPLATE,
            pico_text      = pico_text,
            criterion_text = criterion.text,
            context_text   = context,
        )

        response = await llm_client.complete(
            prompt          = prompt,
            system          = (
                "You are a precise systematic review screener. "
                "Reply only with the requested JSON."
            ),
            model           = llm_client.GPT_MODEL,
            temperature     = 0.0,
            max_tokens      = 256,
            response_format = "json",
        )

        parsed     = response.parsed_json or {}
        satisfies  = parsed.get("satisfies",     False)
        confidence = float(parsed.get("confidence",  0.5))
        span       = str(parsed.get("evidence_span", "")).strip()
        confidence = max(0.0, min(1.0, confidence))

        # Compute p_satisfy
        if satisfies is True or satisfies == "true":
            p_satisfy = confidence
        else:
            p_satisfy = min(1.0 - confidence, _FALSE_CAP)

        # Step 6: Span verification + hallucination penalty
        hallucination = False
        verified      = False
        if span:
            verified = verifier.verify(span, document)
            if not verified:
                hallucination = True
                p_satisfy    *= _HALLUCINATION_MUL
                logger.debug(
                    "CriterionAwareRAG: hallucination flag for %s / %s",
                    document.record_id, criterion.criterion_id,
                )

        source_section = self._infer_section(span, document)

        return CriterionResult(
            criterion_id           = criterion.criterion_id,
            p_satisfy              = max(0.0, min(1.0, p_satisfy)),
            decision               = _decide(p_satisfy),
            evidence_span          = span or None,
            evidence_span_verified = verified,
            source_section         = source_section,
            hallucination_flag     = hallucination,
            llm_raw_response       = response.content,
        )

    # ------------------------------------------------------------------
    # Index cache
    # ------------------------------------------------------------------

    def _get_or_build_index(
        self,
        document: StructuredDocument,
        encoder:  Any,
    ) -> _DocumentIndex:
        rid = document.record_id
        if rid not in self._index_cache:
            logger.debug(
                "CriterionAwareRAG: building document index for %s", rid
            )
            self._index_cache[rid] = _DocumentIndex.build(document, encoder)
        return self._index_cache[rid]

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(
        sentences: List[str],
        hits:      List[Tuple[int, float]],
    ) -> str:
        """
        Concatenate top-scored sentences up to _TOKEN_BUDGET tokens.
        Preserves sentence order (sorted by position, not score).
        """
        # Sort by original position so context reads naturally
        ordered = sorted(hits, key=lambda x: x[0])

        parts: List[str] = []
        total_tokens = 0
        for idx, _score in ordered:
            sent = sentences[idx]
            t    = _approx_tokens(sent)
            if total_tokens + t > _TOKEN_BUDGET:
                break
            parts.append(sent)
            total_tokens += t

        return " ".join(parts)

    @staticmethod
    def _infer_section(span: str, document: StructuredDocument) -> SectionLabel:
        if not span:
            return SectionLabel.OTHER
        for label_val, text in document.sections.items():
            if span in text:
                try:
                    return SectionLabel(label_val)
                except ValueError:
                    return SectionLabel.OTHER
        return SectionLabel.OTHER
