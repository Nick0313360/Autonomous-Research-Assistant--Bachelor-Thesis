"""
tier2_screening/pico_extractor.py
=====================================
Extracts PICO elements from a full-text document.

Two-pass approach
-----------------
Pass 1 — keyword scan
    For each sentence in Methods + Results sections, check for PICO-specific
    keyword signatures.  The top 10 candidates per element are forwarded to
    the LLM in Pass 2.

Pass 2 — LLM extraction
    A structured prompt (config/prompts/pico_extraction.txt) asks the LLM to
    identify the most precise PICO description from the candidates.
    Returns JSON: {P, I, C, O} with text + source fields.

Cross-validation
----------------
The extracted PICO is embedded and compared against the abstract-stage
pico_embedding stored in AbstractContext.  If cosine similarity < 0.60 a
"abstract_fulltext_pico_mismatch" flag is set in the PICORecord.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, List, Optional

import numpy as np

from models.data_classes import (
    AbstractContext,
    ExtractedElement,
    PICO,
    PICORecord,
    ReviewProtocol,
    SectionLabel,
    StructuredDocument,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH        = Path(__file__).parent.parent / "config" / "prompts" / "pico_extraction.txt"
_MAX_CANDIDATES     = 10     # sentences forwarded to LLM per PICO element
_ALIGNMENT_THRESH   = 0.60   # cosine similarity for abstract/fulltext PICO agreement
_MISMATCH_FLAG      = "abstract_fulltext_pico_mismatch"

# ---------------------------------------------------------------------------
# Keyword signatures (lowercase substrings) for each PICO element
# ---------------------------------------------------------------------------

_POP_KEYWORDS = (
    "patient", "participant", "subject", "n=", "sample", "cohort",
    "population", "adult", "child", "men", "women", "aged", "enrolled",
    "recruited", "inclusion criteria",
)
_INT_KEYWORDS = (
    "treat", "therap", "drug", "medication", "intervent", "dose",
    " mg ", " g ", "regimen", "surgery", "procedure", "administered",
    "received", "assigned",
)
_COM_KEYWORDS = (
    "control", "placebo", "comparator", "comparison", "versus", " vs ",
    "standard care", "usual care", "sham",
)
_OUT_KEYWORDS = (
    "outcome", "mortality", "survival", "efficacy", "effect",
    "measure", "endpoint", "assess", "rate", "score", "event",
    "reduction", "incidence", "risk", "hazard",
)


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _load_template() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    # Inline fallback
    return (
        "Extract PICO elements from the following candidate sentences.\n\n"
        "Target PICO:\n{pico_target}\n\n"
        "Eligibility criteria:\n{eligibility_criteria}\n\n"
        "Population candidates:\n{population_candidates}\n\n"
        "Intervention candidates:\n{intervention_candidates}\n\n"
        "Comparator candidates:\n{comparator_candidates}\n\n"
        "Outcome candidates:\n{outcome_candidates}\n\n"
        "Reply with JSON only: "
        '{"P":{"text":"...","source":"..."},'
        '"I":{"text":"...","source":"..."},'
        '"C":{"text":"...","source":"..."},'
        '"O":[{"text":"...","source":"..."}]}'
    )


_TEMPLATE = _load_template()


def _fill_template(template: str, **kwargs: str) -> str:
    """Safely substitute named placeholders without interpreting other braces."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def _format_candidates(sentences: List[str]) -> str:
    if not sentences:
        return "(none found)"
    return "\n".join(f"- {s}" for s in sentences)


def _format_eligibility(protocol: ReviewProtocol) -> str:
    parts = [c.text for c in protocol.inclusion_criteria]
    return "\n".join(f"- {t}" for t in parts) if parts else "(not specified)"


def _format_pico_target(protocol: ReviewProtocol) -> str:
    p = protocol.pico
    return (
        f"Population: {p.population}\n"
        f"Intervention: {p.intervention}\n"
        f"Comparator: {p.comparator}\n"
        f"Outcome: {p.outcome}"
    )


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


# ---------------------------------------------------------------------------
# PICOExtractor
# ---------------------------------------------------------------------------

class PICOExtractor:
    """
    Extracts PICO elements from a full-text StructuredDocument.

    Usage
    -----
    extractor = PICOExtractor()
    pico_record = await extractor.extract(document, protocol, abstract_context,
                                          encoder, llm_client)
    """

    async def extract(
        self,
        document:         StructuredDocument,
        protocol:         ReviewProtocol,
        abstract_context: AbstractContext,
        encoder:          Any,    # SharedEncoderService
        llm_client:       Any,    # LLMClient
    ) -> PICORecord:
        """
        Parameters
        ----------
        document :         Parsed full-text document.
        protocol :         Review protocol (target PICO + eligibility criteria).
        abstract_context : Abstract-screening output (provides pico_embedding).
        encoder :          SharedEncoderService.
        llm_client :       LLMClient.

        Returns
        -------
        PICORecord with extracted elements and alignment score.
        """
        try:
            return await self._do_extract(
                document, protocol, abstract_context, encoder, llm_client
            )
        except Exception as exc:
            logger.warning(
                "PICOExtractor: extraction failed for %s: %s",
                document.record_id, exc,
            )
            return self._fallback_record(protocol)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _do_extract(
        self,
        document:         StructuredDocument,
        protocol:         ReviewProtocol,
        abstract_context: AbstractContext,
        encoder:          Any,
        llm_client:       Any,
    ) -> PICORecord:
        # ---- Pass 1: keyword scan ----------------------------------------
        sentences = self._collect_sentences(document)
        pop_cands = self._filter(sentences, _POP_KEYWORDS)
        int_cands = self._filter(sentences, _INT_KEYWORDS)
        com_cands = self._filter(sentences, _COM_KEYWORDS)
        out_cands = self._filter(sentences, _OUT_KEYWORDS)

        # ---- Pass 2: LLM extraction --------------------------------------
        prompt = _fill_template(
            _TEMPLATE,
            pico_target              = _format_pico_target(protocol),
            eligibility_criteria     = _format_eligibility(protocol),
            population_candidates    = _format_candidates(pop_cands),
            intervention_candidates  = _format_candidates(int_cands),
            comparator_candidates    = _format_candidates(com_cands),
            outcome_candidates       = _format_candidates(out_cands),
        )

        response = await llm_client.complete(
            prompt          = prompt,
            system          = (
                "You are a systematic review data extractor. "
                "Reply only with the requested JSON."
            ),
            model           = llm_client.GPT_MODEL,
            temperature     = 0.0,
            max_tokens      = 512,
            response_format = "json",
        )

        parsed = response.parsed_json or {}

        pop_elem  = self._parse_element(parsed.get("P"))
        int_elem  = self._parse_element(parsed.get("I"))
        com_elem  = self._parse_element(parsed.get("C"))
        out_elems = self._parse_outcome_list(parsed.get("O"))

        # Fallback: use best keyword candidates if LLM returned nothing
        if pop_elem is None:
            pop_elem = self._element_from_candidates(pop_cands, "population")
        if int_elem is None:
            int_elem = self._element_from_candidates(int_cands, "intervention")

        # Population and intervention are required
        if pop_elem is None:
            pop_elem = ExtractedElement(
                text="not identified", source_sentence="", confidence=0.1
            )
        if int_elem is None:
            int_elem = ExtractedElement(
                text="not identified", source_sentence="", confidence=0.1
            )
        if not out_elems:
            out_elems = [
                self._element_from_candidates(out_cands, "outcome")
                or ExtractedElement(
                    text="not identified", source_sentence="", confidence=0.1
                )
            ]

        # ---- Cross-validation: embed extracted PICO and compare ----------
        extracted_pico = PICO(
            population   = pop_elem.text,
            intervention = int_elem.text,
            comparator   = com_elem.text if com_elem else "not specified",
            outcome      = out_elems[0].text if out_elems else "not specified",
            study_design = "extracted from full text",
        )
        fulltext_pico_emb = encoder.embed_pico(extracted_pico)

        abstract_pico_emb = np.array(
            abstract_context.pico_embedding, dtype=np.float32
        )
        alignment = _cosine(abstract_pico_emb, fulltext_pico_emb)
        alignment = max(0.0, min(1.0, float(alignment)))

        mismatch_flags: List[str] = []
        if alignment < _ALIGNMENT_THRESH:
            mismatch_flags.append(_MISMATCH_FLAG)
            logger.info(
                "PICOExtractor: PICO mismatch for %s (alignment=%.2f < %.2f)",
                document.record_id, alignment, _ALIGNMENT_THRESH,
            )

        return PICORecord(
            population          = pop_elem,
            intervention        = int_elem,
            outcomes            = out_elems,
            comparator          = com_elem,
            pico_alignment_score = alignment,
            pico_mismatch_flags = mismatch_flags,
        )

    # ------------------------------------------------------------------
    # Pass 1: sentence collection and keyword filtering
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_sentences(document: StructuredDocument) -> List[str]:
        """Return sentences from METHODS and RESULTS sections."""
        text = (
            document.sections.get(SectionLabel.METHODS.value, "")
            + "\n"
            + document.sections.get(SectionLabel.RESULTS.value, "")
        ).strip()

        if not text:
            # Fallback to all sections
            text = " ".join(document.sections.values())

        # Split on sentence boundaries (period/exclamation/question + whitespace)
        raw = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in raw if len(s.strip()) > 15]

    @staticmethod
    def _filter(sentences: List[str], keywords: tuple) -> List[str]:
        """Return up to _MAX_CANDIDATES sentences that contain any keyword."""
        hits: List[str] = []
        lower_sents = [(s, s.lower()) for s in sentences]
        for sent, low in lower_sents:
            for kw in keywords:
                if kw in low:
                    hits.append(sent)
                    break
            if len(hits) >= _MAX_CANDIDATES:
                break
        return hits

    # ------------------------------------------------------------------
    # Pass 2: parsing LLM output
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_element(raw: Any) -> Optional[ExtractedElement]:
        if not isinstance(raw, dict):
            return None
        text   = str(raw.get("text") or "").strip()
        source = str(raw.get("source") or "").strip()
        if not text or text.lower() in ("null", "none", "not identified", "n/a"):
            return None
        return ExtractedElement(
            text            = text,
            source_sentence = source,
            confidence      = 0.8,
        )

    @staticmethod
    def _parse_outcome_list(raw: Any) -> List[ExtractedElement]:
        if not isinstance(raw, list):
            if isinstance(raw, dict):
                raw = [raw]
            else:
                return []
        results: List[ExtractedElement] = []
        for item in raw:
            elem = PICOExtractor._parse_element(item)
            if elem is not None:
                results.append(elem)
        return results

    @staticmethod
    def _element_from_candidates(
        candidates: List[str],
        label:      str,
    ) -> Optional[ExtractedElement]:
        if not candidates:
            return None
        best = candidates[0]
        return ExtractedElement(
            text            = best[:200],
            source_sentence = best,
            confidence      = 0.4,
        )

    # ------------------------------------------------------------------
    # Fallback PICORecord when extraction entirely fails
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_record(protocol: ReviewProtocol) -> PICORecord:
        """Return a PICORecord populated from the protocol targets at low confidence."""
        p = protocol.pico
        return PICORecord(
            population   = ExtractedElement(
                text=p.population, source_sentence="", confidence=0.1
            ),
            intervention = ExtractedElement(
                text=p.intervention, source_sentence="", confidence=0.1
            ),
            outcomes     = [ExtractedElement(
                text=p.outcome, source_sentence="", confidence=0.1
            )],
            comparator   = ExtractedElement(
                text=p.comparator, source_sentence="", confidence=0.1
            ),
            pico_alignment_score = 0.0,
            pico_mismatch_flags  = ["extraction_failed"],
        )
