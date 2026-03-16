"""
search_query.py — Structured Search Query Schema
==================================================
Design Patterns: Value Object + Strategy Pattern (QueryBuilder)

CORE DESIGN DECISION — Why PICO fields exist and how they map to queries
-------------------------------------------------------------------------
The bug that produced "Molar Incisor Hypomineralization" in an AI search:

  Old approach: split research question into tokens → OR all tokens
  → "systematic OR review OR large OR language OR models"
  → matches ANY paper mentioning ANY of those common words on PubMed
  → completely wrong results

  Correct PubMed model:
  ┌─────────────────────────────────────────────────────────────────┐
  │  Each PICO slot = ONE concept  (AND between slots)              │
  │  Within a slot  = synonyms     (OR between them)                │
  │                                                                 │
  │  population   = "systematic review, literature review"          │
  │  intervention = "large language model, LLM, AI agent, GPT"      │
  │                                                                 │
  │  → ("systematic review"[TIAB] OR "literature review"[TIAB])     │
  │    AND                                                          │
  │    ("large language model"[TIAB] OR LLM[TIAB] OR               │
  │     "AI agent"[TIAB] OR GPT[TIAB])                              │
  │                                                                 │
  │  PubMed must find papers about BOTH concepts simultaneously.    │
  └─────────────────────────────────────────────────────────────────┘

  Semantic Scholar: uses research_question verbatim (its own relevance
  engine). Injecting all PICO slots degrades S2 results.

IMPORTANT FOR THE USER
-----------------------
For each PICO slot, provide comma-separated SYNONYMS for that concept.
More synonyms = higher recall without losing precision.

  population   → "systematic review, literature review, scoping review"
  intervention → "large language model, LLM, GPT, AI agent, machine learning"
  outcome      → "PRISMA, precision, recall, accuracy, screening"
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core Value Object
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SearchQuery:
    """
    Immutable validated container for a literature search request.

    Mandatory
    ---------
    research_question : str
        Plain-English question. Used verbatim as Semantic Scholar query
        and for display/logging. Minimum required input.

    PICO slots (optional but critical for PubMed precision)
    -------------------------------------------------------
    Each slot = one concept. Use comma-separated synonyms within a slot.

    population   : domain/subject  e.g. "systematic review, literature review"
    intervention : method/tool     e.g. "large language model, LLM, GPT, AI agent"
    comparison   : baseline        e.g. "manual review, human reviewer"
    outcome      : metric          e.g. "PRISMA, precision, recall, screening"

    domain_keywords : List[str]
        Anchor terms for the LLM refiner. Prevents off-topic expansion terms.
        Auto-derived from PICO slots if not provided explicitly.

    year_range : (int, int)
        Inclusive publication year filter e.g. (2018, 2024).

    max_papers_per_db : int
        Hard cap per database. Max 1000 (S2 API hard limit for bulk endpoint).
    """

    research_question: str
    population: Optional[str] = None
    intervention: Optional[str] = None
    comparison: Optional[str] = None
    outcome: Optional[str] = None
    domain_keywords: List[str] = field(default_factory=list)
    year_range: Optional[tuple] = None
    max_papers_per_db: int = 500

    def __post_init__(self):
        if not self.research_question or not self.research_question.strip():
            raise ValueError("research_question is mandatory and cannot be empty.")
        if self.max_papers_per_db < 1 or self.max_papers_per_db > 1000:
            raise ValueError("max_papers_per_db must be between 1 and 1000.")
        if self.year_range is not None:
            start, end = self.year_range
            if start > end:
                raise ValueError(f"year_range start ({start}) must be <= end ({end}).")

    def effective_domain_keywords(self) -> List[str]:
        """
        Returns domain_keywords if set, otherwise auto-derives from PICO slots.
        Used by the LLM refiner to validate expansion terms.
        """
        if self.domain_keywords:
            return list(self.domain_keywords)
        derived = []
        for slot in [self.population, self.intervention, self.outcome]:
            if slot:
                first = slot.split(",")[0].strip()
                if first:
                    derived.append(first)
        return derived

    def to_dict(self) -> dict:
        return {
            "research_question": self.research_question,
            "population": self.population,
            "intervention": self.intervention,
            "comparison": self.comparison,
            "outcome": self.outcome,
            "domain_keywords": list(self.domain_keywords),
            "year_range": list(self.year_range) if self.year_range else None,
            "max_papers_per_db": self.max_papers_per_db,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: dict) -> "SearchQuery":
        yr = d.get("year_range")
        return cls(
            research_question=d["research_question"],
            population=d.get("population"),
            intervention=d.get("intervention"),
            comparison=d.get("comparison"),
            outcome=d.get("outcome"),
            domain_keywords=d.get("domain_keywords", []),
            year_range=tuple(yr) if yr else None,
            max_papers_per_db=d.get("max_papers_per_db", 500),
        )


# ---------------------------------------------------------------------------
# Query Builder — Strategy Pattern
# ---------------------------------------------------------------------------

class QueryBuilder:
    """
    Converts a SearchQuery into database-specific query strings.

    PubMed:           field-tagged Boolean  (PICO slots AND-ed, synonyms OR-ed)
    Semantic Scholar: research_question as-is (its own relevance engine)
    """

    _PUBMED_MAX_LEN   = 800
    _SEMANTIC_MAX_LEN = 300   # keep S2 query focused; longer hurts relevance

    @staticmethod
    def build_pubmed(sq: SearchQuery) -> str:
        """
        Builds a PubMed [Title/Abstract] Boolean query.

        Structure: (slot1_syn1 OR slot1_syn2) AND (slot2_syn1 OR ...) ...

        Fallback when no PICO slots are provided: wraps the research question
        as a quoted phrase — still vastly more precise than token-OR.
        """
        concept_groups: List[str] = []

        for slot in [sq.population, sq.intervention, sq.comparison, sq.outcome]:
            if slot:
                group = _pubmed_concept_group(slot)
                if group:
                    concept_groups.append(group)

        # Fallback: no PICO → phrase-search the whole research question
        if not concept_groups:
            phrase = sq.research_question.strip()
            concept_groups.append(f'"{phrase}"[Title/Abstract]')

        query = " AND ".join(concept_groups)

        if sq.year_range:
            query += f' AND ("{sq.year_range[0]}"[PDAT]:"{sq.year_range[1]}"[PDAT])'

        return _truncate(query, QueryBuilder._PUBMED_MAX_LEN)

    @staticmethod
    def build_semantic(sq: SearchQuery) -> str:
        """
        Builds a Semantic Scholar bulk-endpoint keyword query.

        WHY NOT use the research question as a sentence:
        ─────────────────────────────────────────────────
        S2 bulk endpoint (/paper/search/bulk) does KEYWORD matching, not
        semantic/NLP search. A sentence like:
          "How do AI agents and large language models automate systematic review?"
        scores poorly because:
          1. Stopwords (how, do, and, large) add noise
          2. Question marks confuse the tokeniser
          3. The endpoint weights term frequency — uncommon technical terms
             should be the core signal, not sentence structure

        Confirmed by observation: sentence query returned 1 paper;
        keyword query returned hundreds.

        STRATEGY — 3-tier keyword assembly:
        ─────────────────────────────────────
        Tier 1 (required): first synonym from population slot (the domain)
                           + first synonym from intervention slot (the tech)
        Tier 2 (context):  up to 2 more intervention synonyms to broaden tech coverage
        Tier 3 (optional): first synonym from outcome if it adds domain specificity

        Result: a compact, high-signal keyword string with the most discriminative
        terms at the front (S2 weights earlier terms more heavily).

        Example output for the systematic review / LLM query:
          "systematic review large language model LLM automation PRISMA"
        """
        terms: List[str] = []

        # Tier 1: domain + primary technology term (always present)
        if sq.population:
            pop_first = _parse_synonyms(sq.population)[0] if _parse_synonyms(sq.population) else ""
            if pop_first:
                terms.append(pop_first)

        if sq.intervention:
            int_synonyms = _parse_synonyms(sq.intervention)
            # Add first synonym (most specific/canonical term)
            if int_synonyms:
                terms.append(int_synonyms[0])
            # Tier 2: add up to 2 more intervention synonyms for tech breadth
            for syn in int_synonyms[1:3]:
                if syn.lower() not in " ".join(terms).lower():
                    terms.append(syn)

        # Tier 3: outcome — only add first term if it's domain-specific
        # (avoids generic terms like "precision" or "accuracy" that appear everywhere)
        if sq.outcome:
            out_first = _parse_synonyms(sq.outcome)[0] if _parse_synonyms(sq.outcome) else ""
            GENERIC_OUTCOME_TERMS = {"precision", "recall", "accuracy", "performance", "results"}
            if out_first and out_first.lower() not in GENERIC_OUTCOME_TERMS:
                terms.append(out_first)

        # Fallback: if no PICO slots provided, extract key nouns from the question
        if not terms:
            # Strip question words and punctuation, keep meaningful tokens
            clean = sq.research_question.strip().rstrip("?").lower()
            SKIP = {"how", "do", "does", "the", "a", "an", "in", "of", "for",
                    "to", "and", "or", "with", "on", "is", "are", "what", "which"}
            tokens = [t.strip(".,;:?!") for t in clean.split()
                      if t.strip(".,;:?!") not in SKIP and len(t) > 2]
            terms = tokens[:6]   # cap at 6 most important tokens

        query = " ".join(terms)
        return _truncate(query, QueryBuilder._SEMANTIC_MAX_LEN)

    @staticmethod
    def preview(sq: SearchQuery) -> str:
        """Human-readable preview of both generated queries."""
        pm = QueryBuilder.build_pubmed(sq)
        s2 = QueryBuilder.build_semantic(sq)
        return (
            f"\n  PubMed ({len(pm)} chars):\n"
            f"    {pm}\n\n"
            f"  Semantic Scholar ({len(s2)} chars):\n"
            f"    {s2}\n"
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _parse_synonyms(slot_text: str) -> List[str]:
    """Split a PICO slot on commas/semicolons and strip whitespace."""
    return [t.strip() for t in re.split(r"[,;]", slot_text) if t.strip()]


def _pubmed_concept_group(slot_text: str) -> str:
    """
    Build one PubMed OR-group from a PICO slot.

    Multi-word → "quoted phrase"[Title/Abstract]
    Single-word → word[Title/Abstract]

    Example: "large language model, LLM, GPT"
    → ("large language model"[Title/Abstract] OR LLM[Title/Abstract] OR GPT[Title/Abstract])
    """
    synonyms = _parse_synonyms(slot_text)
    if not synonyms:
        return ""

    tagged = []
    for term in synonyms:
        if " " in term:
            tagged.append(f'"{term}"[Title/Abstract]')
        else:
            tagged.append(f"{term}[Title/Abstract]")

    if len(tagged) == 1:
        return tagged[0]
    return "(" + " OR ".join(tagged) + ")"


def _truncate(query: str, max_len: int) -> str:
    """Truncate at last word boundary. Warns if truncation happens."""
    if len(query) <= max_len:
        return query
    cut = query[:max_len].rfind(" ")
    result = query[:cut] if cut > 0 else query[:max_len]
    logger.warning("Query truncated to %d chars.", max_len)
    return result


# ---------------------------------------------------------------------------
# Interactive CLI
# ---------------------------------------------------------------------------

def prompt_search_query() -> SearchQuery:
    """
    Guided interactive query builder.

    Explains the AND/OR PICO structure to the user before asking for input.
    """
    print("\n" + "="*65)
    print("  LITERATURE SEARCH — Structured Query Builder")
    print("="*65)
    print("""
How PICO fields work:
  Each field = ONE concept (fields are AND-ed together in PubMed)
  Within a field: list synonyms separated by commas (OR-ed)

  Example for "AI agents for automated systematic review":
    Population  : systematic review, literature review, scoping review
    Intervention: large language model, LLM, GPT, AI agent, NLP

  More synonyms = higher recall while keeping precision.
  Press ENTER to skip optional fields.
""")

    rq = input("🔬 Research question (required):\n  > ").strip()
    while not rq:
        print("  ⚠️  Cannot be empty.")
        rq = input("  > ").strip()

    print("\n─── PICO concept slots ─────────────────────────────────────────")
    population   = input("👥 Population / domain   (e.g. systematic review, literature review)\n  > ").strip() or None
    intervention = input("⚙️  Intervention / method  (e.g. large language model, LLM, GPT, AI agent)\n  > ").strip() or None
    comparison   = input("↔️  Comparison (optional)  (e.g. manual review, human reviewer)\n  > ").strip() or None
    outcome      = input("📊 Outcome / metric       (e.g. PRISMA, precision, recall, screening)\n  > ").strip() or None

    dk_raw = input(
        "\n🔖 Domain anchor keywords (comma-separated, blocks off-topic LLM expansions)\n"
        "   Leave blank to auto-derive from PICO fields:\n  > "
    ).strip()
    domain_keywords = [k.strip() for k in dk_raw.split(",") if k.strip()] if dk_raw else []

    yr_raw = input("\n📅 Year range e.g. 2018-2024  (ENTER to skip):\n  > ").strip()
    year_range = None
    if yr_raw:
        try:
            parts = yr_raw.split("-")
            year_range = (int(parts[0].strip()), int(parts[1].strip()))
        except Exception:
            print("  ⚠️  Could not parse — skipping year range.")

    max_raw = input("\n📦 Max papers per database (1–1000, default 500):\n  > ").strip()
    try:
        max_papers = int(max_raw) if max_raw else 500
        max_papers = max(1, min(max_papers, 1000))
    except ValueError:
        print("  ⚠️  Invalid — using 500.")
        max_papers = 500

    sq = SearchQuery(
        research_question=rq,
        population=population,
        intervention=intervention,
        comparison=comparison,
        outcome=outcome,
        domain_keywords=domain_keywords,
        year_range=year_range,
        max_papers_per_db=max_papers,
    )

    print("\n✅ Query constructed:")
    print(sq.to_json())
    print(QueryBuilder.preview(sq))
    return sq