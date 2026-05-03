"""
tier3_synthesis/data_extractor.py
=====================================
Structured data extraction from included full-text documents.

For each document, one LLM call is made per standard extraction field using
the gpt-oss:120b model (fast/bulk).  Evidence spans are verified with
SpanVerifier; unverified spans set verified=False.

Standard fields
---------------
sample_size, study_design, population_description,
intervention_description, primary_outcome, follow_up

Concurrency
-----------
Fields for a single document are extracted concurrently.
Documents are processed sequentially to keep memory usage bounded.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.data_classes import ReviewProtocol, SectionLabel, StructuredDocument
from tier2_screening.span_verifier import SpanVerifier

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "config" / "prompts" / "data_extraction.txt"
_CONTEXT_CHARS = 3_000  # chars from Methods+Results fed to the LLM

# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ExtractedField:
    value:       Optional[str]
    source_span: str
    confidence:  float
    verified:    bool

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


@dataclass
class ExtractedData:
    study_id: str
    fields:   Dict[str, ExtractedField] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------

_FIELDS: Dict[str, str] = {
    "sample_size":              "the total number of participants or patients enrolled",
    "study_design":             "the study design (e.g., RCT, cohort, case-control, cross-sectional)",
    "population_description":   "a description of the study population including key inclusion criteria",
    "intervention_description": "a description of the intervention or exposure",
    "primary_outcome":          "the primary outcome measure or endpoint",
    "follow_up":                "the follow-up duration or observation period",
}


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------

def _load_template() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return (
        "Extract {field_name} ({field_description}) from:\n{context_text}\n\n"
        'Reply JSON: {"value": "...", "source_span": "...", "confidence": 0.0}'
    )


_TEMPLATE = _load_template()


def _fill_template(template: str, **kwargs: str) -> str:
    """Safely substitute named placeholders without interpreting other braces."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


# ---------------------------------------------------------------------------
# DataExtractionAgent
# ---------------------------------------------------------------------------

class DataExtractionAgent:
    """
    Extracts structured fields from full-text documents.

    Usage
    -----
    agent = DataExtractionAgent()
    results = await agent.extract_batch(documents, protocol, llm_client)
    """

    def __init__(self) -> None:
        self._verifier = SpanVerifier()

    async def extract_batch(
        self,
        documents:  List[StructuredDocument],
        protocol:   ReviewProtocol,
        llm_client: Any,
    ) -> List[ExtractedData]:
        """
        Extract standard fields from each document.

        Parameters
        ----------
        documents :  Included full-text documents.
        protocol :   Review protocol (for context).
        llm_client : LLMClient.

        Returns
        -------
        List[ExtractedData] in the same order as documents.
        """
        results: List[ExtractedData] = []
        for doc in documents:
            try:
                extracted = await self._extract_one(doc, protocol, llm_client)
            except Exception as exc:
                logger.warning(
                    "DataExtractionAgent: extraction failed for %s: %s",
                    doc.record_id, exc,
                )
                extracted = ExtractedData(study_id=doc.record_id)
            results.append(extracted)

        logger.info(
            "DataExtractionAgent: extracted data from %d/%d documents",
            sum(1 for r in results if r.fields),
            len(results),
        )
        return results

    async def _extract_one(
        self,
        document:   StructuredDocument,
        protocol:   ReviewProtocol,
        llm_client: Any,
    ) -> ExtractedData:
        """Extract all standard fields concurrently for one document."""
        context_text = (
            document.sections.get(SectionLabel.METHODS.value, "")
            + " "
            + document.sections.get(SectionLabel.RESULTS.value, "")
        )[:_CONTEXT_CHARS]

        # Run all field extractions concurrently
        tasks = {
            fname: self._extract_field(
                field_name        = fname,
                field_description = fdesc,
                context_text      = context_text,
                document          = document,
                llm_client        = llm_client,
            )
            for fname, fdesc in _FIELDS.items()
        }

        field_results: Dict[str, ExtractedField] = {}
        values = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for fname, result in zip(tasks.keys(), values):
            if isinstance(result, Exception):
                logger.debug(
                    "DataExtractionAgent: field '%s' failed for %s: %s",
                    fname, document.record_id, result,
                )
                field_results[fname] = ExtractedField(
                    value=None, source_span="", confidence=0.0, verified=False
                )
            else:
                field_results[fname] = result

        return ExtractedData(study_id=document.record_id, fields=field_results)

    async def _extract_field(
        self,
        field_name:        str,
        field_description: str,
        context_text:      str,
        document:          StructuredDocument,
        llm_client:        Any,
    ) -> ExtractedField:
        prompt = _fill_template(
            _TEMPLATE,
            field_name        = field_name,
            field_description = field_description,
            context_text      = context_text,
        )

        response = await llm_client.complete(
            prompt          = prompt,
            system          = (
                "You are a systematic review data extractor. "
                "Reply only with the requested JSON."
            ),
            model           = llm_client.GPT_MODEL,
            temperature     = 0.0,
            max_tokens      = 192,
            response_format = "json",
        )

        parsed     = response.parsed_json or {}
        raw_value  = parsed.get("value")
        value      = str(raw_value).strip() if raw_value not in (None, "null", "") else None
        source_span = str(parsed.get("source_span", "")).strip()
        confidence  = float(parsed.get("confidence", 0.5))
        confidence  = max(0.0, min(1.0, confidence))

        # Verify span against document text
        verified = False
        if source_span:
            verified = self._verifier.verify(source_span, document)
            if not verified:
                logger.debug(
                    "DataExtractionAgent: unverified span for field '%s' in %s",
                    field_name, document.record_id,
                )

        return ExtractedField(
            value       = value,
            source_span = source_span,
            confidence  = confidence,
            verified    = verified,
        )
