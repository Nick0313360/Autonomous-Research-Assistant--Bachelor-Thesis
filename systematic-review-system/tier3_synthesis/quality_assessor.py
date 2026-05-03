"""
tier3_synthesis/quality_assessor.py
=======================================
Methodological quality and risk-of-bias assessment.

Study design detection
----------------------
If extracted study_design contains "random" → Cochrane RoB 2 (5 domains).
Otherwise                                   → Simplified NOS (3 domains).

Cochrane RoB 2 domains
-----------------------
D1  Randomization process
D2  Deviations from intended interventions
D3  Missing outcome data
D4  Measurement of the outcome
D5  Selection of reported results

NOS domains (simplified)
------------------------
S1  Selection bias
S2  Comparability
S3  Outcome assessment

Overall judgment
----------------
"high"          if any domain is "high"
"some_concerns" if any domain is "some_concerns" (and none is "high")
"low"           if all domains are "low"

LLM: claude-sonnet-4-6 (llm_client.CLAUDE_MODEL) — per-domain call.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.data_classes import SectionLabel, StructuredDocument
from tier3_synthesis.data_extractor import ExtractedData

logger = logging.getLogger(__name__)

_ROB2_PROMPT_PATH = Path(__file__).parent.parent / "config" / "prompts" / "rob2_domain.txt"
_NOS_PROMPT_PATH  = Path(__file__).parent.parent / "config" / "prompts" / "nos_domain.txt"
_METHODS_CHARS    = 3_000

# ---------------------------------------------------------------------------
# Judgment constants
# ---------------------------------------------------------------------------

LOW           = "low"
SOME_CONCERNS = "some_concerns"
HIGH          = "high"
_VALID_JUDGMENTS = {LOW, SOME_CONCERNS, HIGH}
_JUDGMENT_RANK   = {LOW: 0, SOME_CONCERNS: 1, HIGH: 2}

# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DomainJudgment:
    domain_id:   str
    domain_name: str
    judgment:    str        # "low" | "some_concerns" | "high"
    rationale:   str
    quote:       str = ""

    def __post_init__(self) -> None:
        if self.judgment not in _VALID_JUDGMENTS:
            self.judgment = SOME_CONCERNS   # safe default


@dataclass
class RoBAssessment:
    study_id:         str
    tool:             str             # "rob2" | "nos"
    domain_judgments: List[DomainJudgment] = field(default_factory=list)
    overall_judgment: str = SOME_CONCERNS

    def __post_init__(self) -> None:
        if self.domain_judgments:
            self.overall_judgment = _aggregate(self.domain_judgments)


def _aggregate(domains: List[DomainJudgment]) -> str:
    best_rank = max(_JUDGMENT_RANK.get(d.judgment, 1) for d in domains)
    return [LOW, SOME_CONCERNS, HIGH][best_rank]


# ---------------------------------------------------------------------------
# Domain definitions
# ---------------------------------------------------------------------------

_ROB2_DOMAINS: Dict[str, Dict[str, str]] = {
    "D1": {
        "name": "Randomization process",
        "questions": (
            "1.1 Was the allocation sequence random?\n"
            "1.2 Was the allocation sequence concealed until participants were enrolled?\n"
            "1.3 Did baseline differences suggest a problem with the randomization process?"
        ),
    },
    "D2": {
        "name": "Deviations from intended interventions",
        "questions": (
            "2.1 Were participants aware of their assigned intervention during the trial?\n"
            "2.2 Were carers and people delivering the interventions aware of assigned intervention?\n"
            "2.3 Were there deviations from the intended intervention that arose because of the trial context?"
        ),
    },
    "D3": {
        "name": "Missing outcome data",
        "questions": (
            "3.1 Were data for this outcome available for all, or nearly all, randomized participants?\n"
            "3.2 If not, is there evidence that the result was not biased by missing outcome data?\n"
            "3.3 Could missingness in the outcome depend on its true value?"
        ),
    },
    "D4": {
        "name": "Measurement of the outcome",
        "questions": (
            "4.1 Was the method of measuring the outcome inappropriate?\n"
            "4.2 Could measurement of the outcome have differed between intervention groups?\n"
            "4.3 Were outcome assessors aware of the intervention received?"
        ),
    },
    "D5": {
        "name": "Selection of the reported result",
        "questions": (
            "5.1 Were the trial's pre-specified primary outcomes reported?\n"
            "5.2 Was the trial registered before enrolment began?\n"
            "5.3 Is the reported result likely selected from multiple eligible outcome measurements?"
        ),
    },
}

_NOS_DOMAINS: Dict[str, Dict[str, str]] = {
    "S1": {
        "name": "Selection",
        "questions": (
            "Is the exposed cohort/case group truly representative of the population?\n"
            "Is the non-exposed cohort/control group drawn from the same community?\n"
            "Was ascertainment of exposure/case status secure (e.g., records, structured interview)?\n"
            "Was the outcome of interest not present at start of study?"
        ),
    },
    "S2": {
        "name": "Comparability",
        "questions": (
            "Are cohorts/cases and controls comparable on the basis of the design or analysis?\n"
            "Were the most important confounders controlled for?\n"
            "Were additional confounders controlled for?"
        ),
    },
    "S3": {
        "name": "Outcome",
        "questions": (
            "Was the assessment of outcome independent and blinded?\n"
            "Was follow-up long enough for outcomes to occur?\n"
            "Was the follow-up of cohorts adequate / was there case-control matching?"
        ),
    },
}

# ---------------------------------------------------------------------------
# Prompt loaders
# ---------------------------------------------------------------------------

def _load_template(path: Path, fallback: str) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else fallback


def _fill_template(template: str, **kwargs: str) -> str:
    """Safely substitute named placeholders without interpreting other braces."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


_ROB2_TEMPLATE = _load_template(
    _ROB2_PROMPT_PATH,
    "Assess RoB2 domain {domain_name}.\nQuestions:\n{signaling_questions}\n"
    "Methods: {methods_text}\n"
    'JSON: {"judgment":"low"|"some_concerns"|"high","rationale":"...","quote":"..."}',
)
_NOS_TEMPLATE = _load_template(
    _NOS_PROMPT_PATH,
    "Assess NOS domain {domain_name}.\nCriteria:\n{criteria}\n"
    "Methods: {methods_text}\n"
    'JSON: {"judgment":"low"|"some_concerns"|"high","rationale":"...","quote":"..."}',
)

# ---------------------------------------------------------------------------
# QualityAssessor
# ---------------------------------------------------------------------------

class QualityAssessor:
    """
    Assesses methodological quality for each included study.

    Uses RoB 2 for RCTs, simplified NOS for observational studies.
    Each domain judgment is made by a separate LLM call (CLAUDE_MODEL).
    """

    async def assess_batch(
        self,
        documents:      List[StructuredDocument],
        extracted_data: List[ExtractedData],
        protocol:       Any,   # ReviewProtocol (unused here, available for subclasses)
        llm_client:     Any,
    ) -> List[Dict]:
        """
        Parameters
        ----------
        documents :      Included full-text documents.
        extracted_data : Per-document extraction results from DataExtractionAgent.
        protocol :       Review protocol.
        llm_client :     LLMClient.

        Returns
        -------
        List[Dict]
            Each dict is the result of dataclasses.asdict(RoBAssessment).
            In document order.
        """
        ext_map: Dict[str, ExtractedData] = {e.study_id: e for e in extracted_data}

        results: List[Dict] = []
        for doc in documents:
            ext = ext_map.get(doc.record_id)
            try:
                assessment = await self._assess_one(doc, ext, llm_client)
            except Exception as exc:
                logger.warning(
                    "QualityAssessor: assessment failed for %s: %s",
                    doc.record_id, exc,
                )
                assessment = RoBAssessment(
                    study_id = doc.record_id,
                    tool     = "unknown",
                    domain_judgments = [],
                    overall_judgment = SOME_CONCERNS,
                )
            results.append(dataclasses.asdict(assessment))

        logger.info(
            "QualityAssessor: assessed %d documents", len(results)
        )
        return results

    # ------------------------------------------------------------------
    # Per-study dispatch
    # ------------------------------------------------------------------

    async def _assess_one(
        self,
        document:      StructuredDocument,
        extracted:     Optional[ExtractedData],
        llm_client:    Any,
    ) -> RoBAssessment:
        methods_text = (
            document.sections.get(SectionLabel.METHODS.value, "")
            + " "
            + document.sections.get(SectionLabel.RESULTS.value, "")
        )[:_METHODS_CHARS]

        # Detect study design
        design = ""
        if extracted and "study_design" in extracted.fields:
            ef = extracted.fields["study_design"]
            if ef.value:
                design = ef.value.lower()

        if "random" in design or "rct" in design:
            return await self._rob2_assess(document.record_id, methods_text, llm_client)
        else:
            return await self._nos_assess(document.record_id, methods_text, llm_client)

    # ------------------------------------------------------------------
    # RoB 2
    # ------------------------------------------------------------------

    async def _rob2_assess(
        self,
        study_id:     str,
        methods_text: str,
        llm_client:   Any,
    ) -> RoBAssessment:
        tasks = {
            did: self._assess_domain(
                template     = _ROB2_TEMPLATE,
                domain_id    = did,
                domain_name  = ddef["name"],
                questions    = ddef["questions"],
                methods_text = methods_text,
                llm_client   = llm_client,
            )
            for did, ddef in _ROB2_DOMAINS.items()
        }
        judgments = await self._gather_domains(tasks)
        return RoBAssessment(
            study_id         = study_id,
            tool             = "rob2",
            domain_judgments = judgments,
        )

    # ------------------------------------------------------------------
    # NOS
    # ------------------------------------------------------------------

    async def _nos_assess(
        self,
        study_id:     str,
        methods_text: str,
        llm_client:   Any,
    ) -> RoBAssessment:
        tasks = {
            did: self._assess_domain(
                template     = _NOS_TEMPLATE,
                domain_id    = did,
                domain_name  = ddef["name"],
                questions    = ddef["questions"],
                methods_text = methods_text,
                llm_client   = llm_client,
            )
            for did, ddef in _NOS_DOMAINS.items()
        }
        judgments = await self._gather_domains(tasks)
        return RoBAssessment(
            study_id         = study_id,
            tool             = "nos",
            domain_judgments = judgments,
        )

    # ------------------------------------------------------------------
    # Single domain LLM call
    # ------------------------------------------------------------------

    async def _assess_domain(
        self,
        template:     str,
        domain_id:    str,
        domain_name:  str,
        questions:    str,
        methods_text: str,
        llm_client:   Any,
    ) -> DomainJudgment:
        # Both templates use either {signaling_questions} (RoB2) or {criteria} (NOS)
        prompt = _fill_template(
            template,
            domain_name         = domain_name,
            signaling_questions = questions,
            criteria            = questions,
            methods_text        = methods_text,
        )

        response = await llm_client.complete(
            prompt          = prompt,
            system          = (
                "You are a systematic review methodologist applying standardised "
                "risk-of-bias assessment tools. Reply only with the requested JSON."
            ),
            model           = llm_client.GPT_MODEL,
            temperature     = 0.0,
            max_tokens      = 256,
            response_format = "json",
        )

        parsed   = response.parsed_json or {}
        judgment = str(parsed.get("judgment", SOME_CONCERNS)).lower().replace(" ", "_")
        if judgment not in _VALID_JUDGMENTS:
            judgment = SOME_CONCERNS

        return DomainJudgment(
            domain_id   = domain_id,
            domain_name = domain_name,
            judgment    = judgment,
            rationale   = str(parsed.get("rationale", "")).strip(),
            quote       = str(parsed.get("quote", "")).strip(),
        )

    # ------------------------------------------------------------------
    # Gather helper
    # ------------------------------------------------------------------

    @staticmethod
    async def _gather_domains(
        tasks: Dict[str, Any],
    ) -> List[DomainJudgment]:
        """Run domain tasks concurrently; substitute SOME_CONCERNS on failure."""
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        judgments: List[DomainJudgment] = []
        for did, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.warning(
                    "QualityAssessor: domain %s assessment failed: %s", did, result
                )
                judgments.append(DomainJudgment(
                    domain_id   = did,
                    domain_name = did,
                    judgment    = SOME_CONCERNS,
                    rationale   = f"Assessment failed: {result}",
                ))
            else:
                judgments.append(result)
        return judgments
