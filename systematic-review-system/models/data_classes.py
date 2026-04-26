from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional, Set
from uuid import uuid4

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Decision(Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    UNCERTAIN = "uncertain"


class Stage(Enum):
    RETRIEVAL = "retrieval"
    ABSTRACT_SCREENING = "abstract_screening"
    FULLTEXT_RETRIEVAL = "fulltext_retrieval"
    FULLTEXT_SCREENING = "fulltext_screening"
    PICO_EXTRACTION = "pico_extraction"
    DECISION_FUSION = "decision_fusion"
    QUALITY_ASSESSMENT = "quality_assessment"


class ScreeningTier(Enum):
    TIER1_DIRECT = "tier1_direct"
    TIER2_HIERARCHICAL = "tier2_hierarchical"
    TIER3_RAG = "tier3_rag"


class SectionLabel(Enum):
    TITLE = "title"
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    CONCLUSION = "conclusion"
    REFERENCES = "references"
    OTHER = "other"


class CriterionType(Enum):
    MANDATORY = "mandatory"
    DESIRABLE = "desirable"


class SearchQuery(BaseModel):
    research_question: str
    population: Optional[str] = None
    intervention: Optional[str] = None
    outcome: Optional[str] = None
    comparison: Optional[str] = None
    domain_keywords: List[str] = []
    year_range: Optional[tuple] = None
    max_papers_per_db: int = 500

    @field_validator("research_question")
    def research_question_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("research_question is mandatory")
        return v

    @field_validator("max_papers_per_db")
    def max_papers_valid(cls, v):
        if v <= 0 or v > 10000:
            raise ValueError("max_papers_per_db must be between 1 and 10000")
        return v


class Paper(BaseModel):
    title: str
    abstract: Optional[str] = None
    doi: Optional[str] = None
    year: Optional[int] = None
    source: str
    pdf_link: Optional[str] = None
    authors: Optional[List[str]] = None
    paper_id: Optional[str] = None
    embedding: Optional[List[float]] = None

    @property
    def paper_id(self) -> str:
        return self.paper_id or self.doi or self.title[:50]

    @field_validator("title", "source")
    def must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("field cannot be empty")
        return v

    @field_validator("year")
    def must_be_year(cls, v):
        if v is None:
            return v
        current_year = date.today().year
        if v <= 0 or v > current_year:
            raise ValueError(f"year {v} is not valid")
        return v


class SearchIteration(BaseModel):
    iteration: int
    query: str
    papers_retrieved: int
    new_papers: int
    terms_added: List[str] = []
    timestamp: Optional[str] = None


class SearchRun(BaseModel):
    run_id: str
    search_query: SearchQuery
    mode: str
    iterations: List[SearchIteration] = []
    final_papers: List[Paper] = []
    created_at: Optional[str] = None


class RefinementResult(BaseModel):
    iteration: int = 0
    accepted_terms: List[str] = []
    rejected_terms: List[str] = []
    expanded_query: str = ""
    llm_raw_output: Optional[str] = None
    error: Optional[str] = None


class TermDecision(BaseModel):
    term: str
    accepted: bool
    reason: str


class ScreeningDecision(BaseModel):
    paper_id: str
    decision: str  # "include", "exclude", "uncertain"
    reason: str
    confidence: Optional[float] = None
    iteration: int = 0


class PRISMALog(BaseModel):
    run_id: str = ""
    identified_pubmed: int = 0
    identified_semantic_scholar: int = 0
    duplicates_removed_by_doi: int = 0
    duplicates_removed_by_title: int = 0
    records_after_deduplication: int = 0
    screened: int = 0
    included: int = 0
    excluded: int = 0
    uncertain: int = 0
    iterations_run: int = 0
    queries_used: List[str] = []
    terms_added_per_iteration: List[str] = []


class ExtractionResult(BaseModel):
    paper_id: str
    study_id: str
    population: Optional[str] = None
    intervention: Optional[str] = None
    comparison: Optional[str] = None
    outcomes: List[str] = []
    results: Optional[str] = None
    conclusions: Optional[str] = None
    limitations: Optional[str] = None


class QualityAssessment(BaseModel):
    paper_id: str
    overall_score: float
    risk_of_bias: str
    methodological_quality: str
    evidence_quality: str
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Dataclasses (v2 redesign)
# ---------------------------------------------------------------------------

@dataclass
class PICO:
    population: str
    intervention: str
    comparator: str
    outcome: str
    study_design: str

    def __post_init__(self) -> None:
        for fname in ("population", "intervention", "comparator", "outcome", "study_design"):
            val = getattr(self, fname)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"PICO.{fname} must be a non-empty string")


@dataclass
class Criterion:
    text: str
    type: CriterionType
    criterion_id: str = field(default_factory=lambda: str(uuid4()))
    pico_element: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Criterion.text must be a non-empty string")
        if not isinstance(self.type, CriterionType):
            raise TypeError(f"Criterion.type must be CriterionType, got {type(self.type)}")


@dataclass
class ReviewProtocol:
    title: str
    research_question: str
    pico: PICO
    inclusion_criteria: List[Criterion]
    exclusion_criteria: List[Criterion]
    target_databases: List[str]
    protocol_id: str = field(default_factory=lambda: str(uuid4()))
    date_range: Optional[tuple[int, int]] = None
    language_restrictions: List[str] = field(default_factory=list)
    max_papers_per_db: int = 500

    def __post_init__(self) -> None:
        for fname in ("title", "research_question"):
            val = getattr(self, fname)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"ReviewProtocol.{fname} must be a non-empty string")
        if self.date_range is not None:
            start, end = self.date_range
            if start > end:
                raise ValueError("ReviewProtocol.date_range start must be <= end")


@dataclass
class CandidateRecord:
    source_database: str
    title: str
    record_id: str = field(default_factory=lambda: str(uuid4()))
    external_id: Optional[str] = None
    abstract: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    retrieval_query_id: Optional[str] = None
    retrieval_timestamp: datetime = field(default_factory=datetime.now)
    deduplication_status: Optional[str] = None

    def __post_init__(self) -> None:
        if self.year is not None:
            current_year = date.today().year
            if not (1000 <= self.year <= current_year):
                raise ValueError(f"CandidateRecord.year {self.year} is out of valid range")


@dataclass
class AbstractContext:
    record_id: str
    abstract_embedding: List[float]
    pico_embedding: List[float]
    retrieval_score: float
    criterion_probabilities: Dict[str, float]
    overall_include_probability: float
    abstract_decision: Decision
    abstract_confidence: float
    screening_method: str
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        for fname in ("retrieval_score", "overall_include_probability", "abstract_confidence"):
            val = getattr(self, fname)
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"AbstractContext.{fname} must be in [0, 1], got {val}")
        for cid, prob in self.criterion_probabilities.items():
            if not (0.0 <= prob <= 1.0):
                raise ValueError(
                    f"AbstractContext.criterion_probabilities[{cid!r}] must be in [0, 1], got {prob}"
                )


@dataclass
class CriterionResult:
    criterion_id: str
    p_satisfy: float
    decision: Decision
    evidence_span: Optional[str] = None
    evidence_span_verified: bool = False
    source_section: SectionLabel = SectionLabel.OTHER
    hallucination_flag: bool = False
    llm_raw_response: Optional[str] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.p_satisfy <= 1.0):
            raise ValueError(f"CriterionResult.p_satisfy must be in [0, 1], got {self.p_satisfy}")


@dataclass
class ExtractedElement:
    text: str
    source_sentence: str
    confidence: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"ExtractedElement.confidence must be in [0, 1], got {self.confidence}")


@dataclass
class PICORecord:
    population: ExtractedElement
    intervention: ExtractedElement
    outcomes: List[ExtractedElement]
    pico_alignment_score: float
    pico_mismatch_flags: List[str] = field(default_factory=list)
    comparator: Optional[ExtractedElement] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.pico_alignment_score <= 1.0):
            raise ValueError(
                f"PICORecord.pico_alignment_score must be in [0, 1], got {self.pico_alignment_score}"
            )


@dataclass
class ScreeningResult:
    record_id: str
    screening_tier: ScreeningTier
    criterion_results: List[CriterionResult]
    final_decision: Decision
    p_include_final: float
    explanation: str
    pico_record: Optional[PICORecord] = None
    exclusion_reason: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not (0.0 <= self.p_include_final <= 1.0):
            raise ValueError(
                f"ScreeningResult.p_include_final must be in [0, 1], got {self.p_include_final}"
            )


@dataclass
class DecisionRecord:
    paper_id: str
    stage: Stage
    decision: Decision
    confidence: float
    inputs: Dict
    outputs: Dict
    model_used: str
    model_version: str
    prompt_template_id: str
    processing_time_ms: int
    token_count_input: int
    token_count_output: int
    record_id: str = field(default_factory=lambda: str(uuid4()))
    flags: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"DecisionRecord.confidence must be in [0, 1], got {self.confidence}")
        if self.processing_time_ms < 0:
            raise ValueError("DecisionRecord.processing_time_ms must be >= 0")
        if self.token_count_input < 0 or self.token_count_output < 0:
            raise ValueError("DecisionRecord token counts must be >= 0")


@dataclass
class PRISMAState:
    review_id: str = field(default_factory=lambda: str(uuid4()))
    stage_counts: Dict[str, int] = field(default_factory=dict)
    exclusion_reasons: Dict[str, int] = field(default_factory=dict)
    query_versions: List[str] = field(default_factory=list)


@dataclass
class FinalDecision:
    decision: Decision
    p_include_final: float
    criterion_probabilities: Dict[str, float]
    explanation: str
    decision_record_id: str
    exclusion_reason: Optional[str] = None
    exclusion_criterion_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.p_include_final <= 1.0):
            raise ValueError(
                f"FinalDecision.p_include_final must be in [0, 1], got {self.p_include_final}"
            )
        for cid, prob in self.criterion_probabilities.items():
            if not (0.0 <= prob <= 1.0):
                raise ValueError(
                    f"FinalDecision.criterion_probabilities[{cid!r}] must be in [0, 1], got {prob}"
                )


@dataclass
class RetrievalResult:
    """Outcome of a full-text retrieval attempt for a single candidate."""
    record_id: str
    success: bool
    pdf_path: Optional[str] = None
    xml_path: Optional[str] = None
    retrieval_source: Optional[str] = None   # "unpaywall" | "europe_pmc" | "pubmed_central"
    failure_reason: Optional[str] = None


@dataclass
class StructuredDocument:
    """Parsed, section-segmented representation of a full-text article."""
    record_id: str
    sections: Dict[str, str]               # SectionLabel.value → text
    section_embeddings: Dict[str, List[float]]  # SectionLabel.value → embedding
    parsing_quality_score: float
    token_count: int
    source_format: str                     # "pdf" | "xml"

    def __post_init__(self) -> None:
        if not (0.0 <= self.parsing_quality_score <= 1.0):
            raise ValueError(
                f"StructuredDocument.parsing_quality_score must be in [0, 1], "
                f"got {self.parsing_quality_score}"
            )
