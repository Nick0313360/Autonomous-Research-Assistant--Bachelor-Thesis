"""
tier2_screening/span_verifier.py
===================================
Verifies that a span of text cited by the LLM actually appears in the
full-text document, guarding against hallucinated evidence.

Algorithm
---------
1. Concatenate all section texts into one string.
2. Exact substring match → True immediately.
3. Sliding window fuzzy match using Levenshtein.ratio():
   - Window size equals len(cited_span).
   - Step = window_size // 2  (50 % overlap).
   - If any window's ratio ≥ (1 - threshold) → True.
4. Return False.

Default threshold=0.15 means ≥ 85 % character-level similarity required.
"""
from __future__ import annotations

import logging
from typing import Optional

from Levenshtein import ratio as lev_ratio

from models.data_classes import StructuredDocument

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 0.15   # accept spans within 15 % edit distance


class SpanVerifier:
    """
    Checks whether an LLM-cited evidence span is grounded in the document.

    Usage
    -----
    verifier = SpanVerifier()
    is_grounded = verifier.verify(cited_span, document)
    """

    def verify(
        self,
        cited_span: str,
        document:   StructuredDocument,
        threshold:  float = _DEFAULT_THRESHOLD,
    ) -> bool:
        """
        Return True if *cited_span* can be found in *document* within *threshold*.

        Parameters
        ----------
        cited_span :
            The verbatim string returned by the LLM as evidence.
        document :
            Parsed full-text document containing section texts.
        threshold :
            Maximum permitted edit-distance fraction.  0.15 → requires
            ≥ 85 % similarity.

        Returns
        -------
        bool
            True  → span is grounded.
            False → span appears to be hallucinated.
        """
        if not cited_span or not cited_span.strip():
            logger.debug("SpanVerifier: empty cited_span → unverified")
            return False

        full_text = self._build_full_text(document)
        if not full_text:
            logger.debug(
                "SpanVerifier: empty document for %s → unverified",
                document.record_id,
            )
            return False

        span = cited_span.strip()

        # 1. Exact match
        if span in full_text:
            return True

        # 2. Case-insensitive exact match
        if span.lower() in full_text.lower():
            return True

        # 3. Sliding window fuzzy match
        span_len = len(span)
        if span_len == 0:
            return False

        text_len  = len(full_text)
        step      = max(1, span_len // 2)
        min_ratio = 1.0 - threshold

        for start in range(0, text_len - span_len + 1, step):
            window = full_text[start : start + span_len]
            if lev_ratio(span, window) >= min_ratio:
                return True

        # Check the last window (avoids off-by-one when text_len-span_len is
        # not a multiple of step)
        if text_len >= span_len:
            last_window = full_text[text_len - span_len :]
            if lev_ratio(span, last_window) >= min_ratio:
                return True

        logger.debug(
            "SpanVerifier: span not found in %s (span_len=%d, doc_len=%d)",
            document.record_id,
            span_len,
            text_len,
        )
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_full_text(document: StructuredDocument) -> str:
        """Concatenate all section texts into a single string."""
        return " ".join(document.sections.values())
