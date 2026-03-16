"""
llm_refiner.py — Controlled, Measurable Query Refinement
=========================================================
Design Patterns & Concepts Used
---------------------------------
1. Guard Clause / Domain Anchoring
   Every LLM-suggested term is validated against the domain_keywords of the
   original SearchQuery using substring and semantic overlap checks BEFORE
   it is accepted. This is the root-cause fix for the "robotics appearing in
   a medical informatics search" bug. Garbage in → garbage blocked.

2. Typed Return Object (RefinementResult dataclass)
   Instead of returning a raw string the refiner now returns a RefinementResult
   that captures: accepted terms, rejected terms, rejection reasons, and the
   expanded query. This makes every refinement step auditable, testable, and
   loggable for PRISMA traceability.

3. Convergence Guard
   A term is rejected if it already appears in the current query string
   (case-insensitive). This prevents the infinite-growth bug where the query
   kept getting longer each iteration without adding new information.

4. Hard Limits via SearchQuery
   max_papers_per_db is now read from the SearchQuery object and forwarded
   to the connectors. The limit is a first-class parameter, not an optional
   keyword argument that was silently ignored.

5. Explicit Error Taxonomy
   LLM calls return a RefinementResult even on failure — callers never have
   to check for None or empty string. Errors are categorised: timeout,
   parse_error, domain_mismatch, already_used.
"""

import os
import time
import logging
from dataclasses import dataclass, field
from typing import List, Set, Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Client
# ---------------------------------------------------------------------------

client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL", "https://inference.mlmp.ti.bfh.ch/api/v1"),
    api_key=os.getenv("OPENAI_API_KEY"),
)

_LLM_MODEL   = os.getenv("OPENAI_MODEL", "gpt-oss:120b")
_LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))  # uni GPU is slow — default 120s
_MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Typed Return Object — makes refinement measurable and testable
# ---------------------------------------------------------------------------

@dataclass
class TermDecision:
    """Captures why a single LLM-suggested term was accepted or rejected."""
    term: str
    accepted: bool
    reason: str          # e.g. "domain_match", "already_in_query", "off_topic"


@dataclass
class RefinementResult:
    """
    Full audit record for one refinement step.

    Fields
    ------
    accepted_terms   : Terms that passed domain validation and are new.
    rejected_terms   : Terms blocked with per-term reasons (testable).
    expanded_query   : The final query string after expansion, or the
                       original query if no terms were accepted.
    llm_raw_output   : The raw comma-separated string the LLM returned.
                       Stored for debugging and reproducibility.
    error            : Non-empty when the LLM call itself failed.
    iteration        : Which refinement iteration this belongs to.
    """
    accepted_terms: List[str] = field(default_factory=list)
    rejected_terms: List[TermDecision] = field(default_factory=list)
    expanded_query: str = ""
    llm_raw_output: str = ""
    error: str = ""
    iteration: int = 0

    @property
    def has_new_terms(self) -> bool:
        return len(self.accepted_terms) > 0

    @property
    def acceptance_rate(self) -> float:
        total = len(self.accepted_terms) + len(self.rejected_terms)
        return len(self.accepted_terms) / total if total > 0 else 0.0

    def summary(self) -> str:
        lines = [
            f"  Iteration  : {self.iteration}",
            f"  LLM output : {self.llm_raw_output[:120]}",
            f"  Accepted   : {self.accepted_terms}",
            f"  Rejected   : {[(d.term, d.reason) for d in self.rejected_terms]}",
            f"  Accept rate: {self.acceptance_rate:.0%}",
        ]
        if self.error:
            lines.append(f"  Error      : {self.error}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Domain Validator — the guard that prevents off-topic term injection
# ---------------------------------------------------------------------------

def _is_domain_relevant(
    term: str,
    domain_keywords: List[str],
    research_question: str,
) -> tuple[bool, str]:
    """
    Checks whether a proposed term is semantically relevant to the research domain.

    Strategy: multi-level inclusion check (fast → slow):
      Level 0 — Known vocabulary: is the term in the built-in SLR/NLP/AI
                 domain vocabulary? Handles acronyms (PICO, MeSH, AMSTAR) and
                 established phrases ("evidence synthesis") that share no words
                 with typical anchor keywords but are definitionally in-domain.
      Level 1 — Direct substring: is any anchor inside the term, or vice versa?
      Level 2 — Word overlap: do the term's tokens appear in any anchor?
      Level 3 — Fail: the term is off-topic.

    Returns (is_relevant: bool, reason: str)
    """
    term_lower = term.lower().strip()

    # ── Level 0: Known SLR / AI / NLP domain vocabulary ─────────────────────
    # Terms that are definitionally part of this research domain but may share
    # no words with the anchor keywords. Maintained as a frozenset for O(1) lookup.
    # Expand this list as your thesis topic evolves.
    _SLR_VOCABULARY: frozenset = frozenset({
        # Systematic review methodology
        "pico", "picos", "prisma", "amstar", "grade", "prospero",
        "evidence synthesis", "evidence-based medicine", "meta-analysis",
        "grey literature", "gray literature", "inclusion criteria",
        "exclusion criteria", "study selection", "data extraction",
        "quality assessment", "risk of bias", "inter-rater reliability",
        "kappa", "cohen kappa", "citation screening", "full-text screening",
        "abstract screening", "title screening", "eligibility criteria",
        "mesh terms", "mesh", "boolean search", "search strategy",
        "bibliographic database", "deduplication", "snowballing",
        # NLP / ML methods relevant to SLR automation
        "active learning", "transfer learning", "fine-tuning", "fine tuning",
        "text classification", "information extraction", "named entity recognition",
        "ner", "relation extraction", "question answering", "summarisation",
        "summarization", "embedding", "sentence embedding", "semantic similarity",
        "zero-shot", "few-shot", "prompt engineering", "chain of thought",
        "retrieval augmented generation", "rag", "vector database",
        "knowledge graph", "ontology", "annotation", "inter-annotator agreement",
        # AI / LLM ecosystem
        "llm", "llms", "gpt", "gpt-4", "gpt4", "claude", "gemini", "mistral",
        "bert", "roberta", "biobert", "pubmedbert", "scispacy",
        "transformer", "attention mechanism", "language model",
        "foundation model", "pre-trained model",
    })

    # Direct vocabulary match
    if term_lower in _SLR_VOCABULARY:
        return True, "domain_match_vocabulary"

    # Partial vocabulary match (term contains a vocabulary phrase)
    for vocab_term in _SLR_VOCABULARY:
        if vocab_term in term_lower or term_lower in vocab_term:
            return True, f"domain_match_vocabulary_partial:{vocab_term}"

    # ── Level 1: Substring containment against anchors ───────────────────────
    anchors = [kw.lower() for kw in domain_keywords] + [research_question.lower()]

    for anchor in anchors:
        if term_lower in anchor or anchor in term_lower:
            return True, "domain_match_substring"

    # ── Level 2: Word overlap ─────────────────────────────────────────────────
    TRIVIAL = {"the", "a", "an", "of", "in", "for", "and", "or", "with", "to", "on",
               "is", "are", "was", "be", "by", "at", "its", "this", "that"}
    term_words = {w for w in term_lower.split() if w not in TRIVIAL and len(w) > 2}
    anchor_words = set()
    for anchor in anchors:
        anchor_words.update(w for w in anchor.split() if w not in TRIVIAL and len(w) > 2)

    overlap = term_words & anchor_words
    if overlap:
        return True, f"domain_match_word_overlap:{','.join(overlap)}"

    return False, "off_topic"


# ---------------------------------------------------------------------------
# Paper sampling and context building
# ---------------------------------------------------------------------------

def _extract_sample(papers: list, n: int = 20) -> list:
    """
    Select a representative sample — prefer papers that have abstracts since
    they give the LLM more signal about relevance.
    """
    with_abstract = [p for p in papers if p.get("abstract")]
    without = [p for p in papers if not p.get("abstract")]
    combined = with_abstract + without
    return combined[:n]


def _build_context(sample_papers: list) -> str:
    """Format paper titles + abstracts into a prompt-friendly block."""
    lines = []
    for i, p in enumerate(sample_papers, 1):
        lines.append(f"\n[{i}] Title: {p['title'][:150]}")
        if p.get("abstract"):
            abstract = p["abstract"][:300] + "…" if len(p["abstract"]) > 300 else p["abstract"]
            lines.append(f"    Abstract: {abstract}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM gap analysis — with retry logic and typed output
# ---------------------------------------------------------------------------

def analyse_query_gaps(
    papers: list,
    original_query: str,
    domain_keywords: List[str],
    used_terms: Set[str],
    iteration: int = 0,
    max_new_terms: int = 5,
) -> RefinementResult:
    """
    Ask the LLM to identify concepts missing from the current query, then
    validate each suggestion before accepting it.

    Parameters
    ----------
    papers          : Current paper pool (we sample from these).
    original_query  : The query string used this iteration (for dedup).
    domain_keywords : Hard domain anchors from SearchQuery.domain_keywords.
                      Used by the domain validator to reject off-topic terms.
    used_terms      : Mutable set of terms already in the query (updated in place).
    iteration       : Current loop counter, stored in RefinementResult.
    max_new_terms   : Hard ceiling on accepted terms per iteration.

    Returns
    -------
    RefinementResult — always returned, even on LLM failure.
    """
    result = RefinementResult(iteration=iteration)

    sample = _extract_sample(papers, n=20)
    context = _build_context(sample)

    # --- Build a domain-aware prompt ---
    # Key change vs original: we explicitly tell the LLM what domain we are
    # in AND show it the anchor keywords. This constrains the output space.
    domain_hint = (
        f"Domain anchors (ALL suggestions must relate to these): {', '.join(domain_keywords)}"
        if domain_keywords else
        "Stay strictly within the research topic of the original query."
    )

    used_hint = ""
    if used_terms:
        used_hint = f"\nAlready used terms (do NOT suggest these again): {', '.join(list(used_terms)[:15])}"

    prompt = f"""You are an expert systematic review search strategist.

Original query:
{original_query}

{domain_hint}{used_hint}

Papers retrieved so far (titles and abstracts):
{context}

Task:
Identify {max_new_terms} NEW, SPECIFIC keywords or short phrases that:
  1. Appear in the papers above
  2. Are MISSING from the original query
  3. Are STRICTLY within the domain defined by the anchors above
  4. Would retrieve MORE relevant papers if added to the query

DO NOT suggest:
  - Generic terms (e.g. "research", "study", "analysis")
  - Terms from other fields (e.g. robotics, chemistry) unless they are a
    core method used in the papers
  - Terms already listed as "already used"

Return ONLY a comma-separated list of terms, nothing else. No explanations.
"""

    # --- LLM call with retry ---
    raw_output = ""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=_LLM_MODEL,
                temperature=0.2,          # lower = more deterministic
                max_tokens=100,           # terms list is short; cap tokens
                messages=[
                    {"role": "system", "content": "You are a systematic review search expert. Reply only with comma-separated terms."},
                    {"role": "user",   "content": prompt},
                ],
                timeout=_LLM_TIMEOUT,
            )
            raw_output = response.choices[0].message.content.strip()
            break
        except Exception as exc:
            logger.warning("LLM attempt %d/%d failed: %s", attempt, _MAX_RETRIES, exc)
            if attempt == _MAX_RETRIES:
                result.error = f"LLM unavailable after {_MAX_RETRIES} retries: {exc}"
                result.expanded_query = original_query
                return result
            time.sleep(2 ** attempt)    # exponential back-off

    result.llm_raw_output = raw_output

    # --- Parse and validate each suggested term ---
    candidate_terms = [t.strip().lower() for t in raw_output.split(",") if t.strip()]

    for term in candidate_terms:
        if not term or len(term) < 3:
            result.rejected_terms.append(TermDecision(term, False, "too_short"))
            continue

        # Guard 1 — already in the query string
        if term in original_query.lower():
            result.rejected_terms.append(TermDecision(term, False, "already_in_query"))
            continue

        # Guard 2 — already used in a previous iteration
        if term in used_terms:
            result.rejected_terms.append(TermDecision(term, False, "already_used"))
            continue

        # Guard 3 — domain relevance check (core fix for off-topic injection)
        relevant, reason = _is_domain_relevant(term, domain_keywords, original_query)
        if not relevant:
            result.rejected_terms.append(TermDecision(term, False, reason))
            logger.info("Term rejected (off-topic): '%s'", term)
            continue

        # Term passed all guards — accept it
        result.accepted_terms.append(term)
        used_terms.add(term)

        if len(result.accepted_terms) >= max_new_terms:
            break   # hard ceiling reached

    # --- Build the expanded query ---
    result.expanded_query = expand_query(original_query, result.accepted_terms)
    return result


# ---------------------------------------------------------------------------
# Query expansion — deterministic, no LLM involved
# ---------------------------------------------------------------------------

def expand_query(original_query: str, new_terms: List[str]) -> str:
    """
    Append accepted terms to the existing query using OR.

    Multi-word terms are quoted to preserve phrase semantics. The function
    is pure (no side effects) and therefore easy to unit-test.

    Max query length is enforced at the SearchQuery / QueryBuilder level;
    this function does not truncate so that the caller has full visibility.
    """
    if not new_terms:
        return original_query

    formatted = []
    for term in new_terms:
        formatted.append(f'"{term}"' if " " in term else term)

    return original_query + " OR " + " OR ".join(formatted)