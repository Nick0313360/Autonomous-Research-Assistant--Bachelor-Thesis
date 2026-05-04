"""
tier1_search/query_builder.py
================================
Builds initial SearchQuery objects from a ReviewProtocol.

Two builders are available:

LLMQueryBuilder (preferred)
    Uses an LLM to decompose PICO into Boolean concept-block queries.
    Populates SearchQuery.pubmed_query_override and .s2_query_override so the
    connectors use the pre-built strings directly.  Falls back to QueryBuilder
    if the LLM call fails or returns unparseable output.

QueryBuilder (rule-based fallback)
    Derives domain_keywords from PICO field phrases via regex splitting.
    No LLM required; used when LLMQueryBuilder is unavailable.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, List, Optional

from models.data_classes import ReviewProtocol, SearchQuery

logger = logging.getLogger(__name__)

_MIN_WORD_LEN = 3

# Words that are too generic to be useful standalone search terms.
# Stripped from the *leading* edge of phrase fragments; discarded when they
# would be the only content in a fragment.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "not", "no", "nor",
    "of", "in", "on", "at", "to", "for", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might",
    "its", "it", "this", "that", "these", "those",
    "other", "others", "another", "such", "some", "any", "all", "both",
    "given", "based", "including", "using", "via", "versus",
    "apparent", "apparently", "commonly", "used",
    "patients", "patient", "studies", "study",
})

# Logical separators that divide a PICO field into distinct phrase fragments.
# Splits on: "and", "or", "with", "for" (word-bounded) and comma/semicolon/slash.
_SPLIT_RE = re.compile(
    r"\s+and\s+|\s+or\s+|\s+with\s+|\s+for\s+|[,;]\s*|\s*/\s*",
    flags=re.IGNORECASE,
)


def _extract_phrases(text: str) -> List[str]:
    """
    Split a PICO field into meaningful keyword phrases.

    Algorithm
    ---------
    1. Split on logical conjunctions / enumerators / prepositions.
    2. Strip parentheses from each fragment.
    3. Strip *leading* stop words (preserves trailing medical nouns such as
       "adult patients" or "airway abnormalities").
    4. Discard fragments with no remaining content word (≥ _MIN_WORD_LEN chars,
       not in _STOPWORDS).
    5. Deduplicate, preserving first-occurrence order.
    """
    parts = _SPLIT_RE.split(text)
    phrases: List[str] = []
    seen: set[str] = set()

    for part in parts:
        part = re.sub(r"[()]", " ", part).strip()
        tokens = part.split()

        # Strip leading stop words
        while tokens and tokens[0].lower() in _STOPWORDS:
            tokens = tokens[1:]

        phrase = " ".join(tokens)

        # Require at least one non-stop content word of meaningful length
        content = [
            w for w in tokens
            if w.lower() not in _STOPWORDS and len(w) >= _MIN_WORD_LEN
        ]
        if not content:
            continue

        key = phrase.lower()
        if key and key not in seen:
            seen.add(key)
            phrases.append(phrase)

    return phrases


class QueryBuilder:
    """
    Converts a ReviewProtocol into a list of SearchQuery objects ready for
    database dispatch.
    """

    def build_initial_queries(self, protocol: ReviewProtocol) -> List[SearchQuery]:
        """
        Parameters
        ----------
        protocol : ReviewProtocol

        Returns
        -------
        List[SearchQuery]
            A single SearchQuery whose domain_keywords are phrase-based terms
            derived from the PICO fields (stop-word filtered, order-preserved).
        """
        pico = protocol.pico
        keywords: List[str] = []
        seen: set[str] = set()

        for field_val in (
            pico.population,
            pico.intervention,
            pico.comparator,
            pico.outcome,
        ):
            for phrase in _extract_phrases(field_val):
                key = phrase.lower()
                if key not in seen:
                    seen.add(key)
                    keywords.append(phrase)

        year_range = None
        if protocol.date_range:
            year_range = protocol.date_range

        query = SearchQuery(
            research_question = protocol.research_question,
            population        = pico.population,
            intervention      = pico.intervention,
            outcome           = pico.outcome,
            comparison        = pico.comparator,
            domain_keywords   = keywords,
            year_range        = year_range,
            max_papers_per_db = protocol.max_papers_per_db,
        )
        return [query]


# ---------------------------------------------------------------------------
# LLM-based query builder
# ---------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """\
You are a systematic review search specialist. Given a PICO research protocol,
translate it into optimised search queries for two academic databases.

STRICT RULES — all must be obeyed without exception:

RULE 1 — Rule of 3 (CRITICAL):
  NEVER wrap a phrase longer than 3 words in quotation marks.
  WRONG: "implementation of a sugar-sweetened beverage tax"[TIAB]
  RIGHT: ("SSB tax"[TIAB] OR "beverage tax"[TIAB] OR "sugar tax"[TIAB])

RULE 2 — Modular Concept Blocks:
  Extract 2–4 CORE CONCEPTS from the PICO. Do NOT copy full PICO sentences.
  Each block: (PrimaryTerm[TIAB] OR Synonym1[TIAB] OR Synonym2[TIAB])
  Combine blocks with AND.

RULE 3 — PubMed Format:
  Apply [TIAB] to each quoted or unquoted term.
  Short abbreviations (SSB, BMI, RCT, etc.) need no quotes.
  Good example:
    (SSB[TIAB] OR "sugar tax"[TIAB] OR "beverage levy"[TIAB])
    AND (obesity[TIAB] OR BMI[TIAB] OR "body weight"[TIAB])

RULE 4 — Semantic Scholar Format:
  The S2 bulk endpoint treats every space-separated word as a required AND.
  Output ONLY 3–5 individual keywords: no quotes, no Boolean operators, no
  multi-word phrases. Pick the most specific, discriminating terms only.
  Good example: sugar tax obesity children

OUTPUT — respond with ONLY this JSON object (no markdown fences, no extra text):
{
  "pubmed_query": "...",
  "semantic_scholar_query": "..."
}
"""


def _build_llm_prompt(protocol: ReviewProtocol) -> str:
    pico = protocol.pico
    return (
        f"Research question: {protocol.research_question}\n\n"
        f"PICO:\n"
        f"  Population:    {pico.population}\n"
        f"  Intervention:  {pico.intervention}\n"
        f"  Comparator:    {pico.comparator}\n"
        f"  Outcome:       {pico.outcome}\n"
    )


def _parse_llm_response(response: Any) -> Optional[tuple[str, str]]:
    """
    Extract (pubmed_query, s2_query) from an LLMResponse.
    Returns None if parsing fails.
    """
    parsed = getattr(response, "parsed_json", None)
    if isinstance(parsed, dict):
        pm = parsed.get("pubmed_query", "").strip()
        s2 = parsed.get("semantic_scholar_query", "").strip()
        if pm and s2:
            return pm, s2

    content = getattr(response, "content", "") or ""
    # Strip optional markdown fences
    content = re.sub(r"```(?:json)?\s*", "", content).strip()
    try:
        obj = json.loads(content)
        pm = obj.get("pubmed_query", "").strip()
        s2 = obj.get("semantic_scholar_query", "").strip()
        if pm and s2:
            return pm, s2
    except (json.JSONDecodeError, AttributeError):
        pass

    # Last-resort regex extraction
    pm_match = re.search(r'"pubmed_query"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    s2_match = re.search(r'"semantic_scholar_query"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    if pm_match and s2_match:
        return pm_match.group(1).strip(), s2_match.group(1).strip()

    return None


class LLMQueryBuilder:
    """
    Translates a ReviewProtocol into SearchQuery objects whose
    pubmed_query_override and s2_query_override fields are pre-built by an LLM.

    Falls back to rule-based QueryBuilder if the LLM call fails or produces
    unparseable output.
    """

    _fallback = QueryBuilder()

    async def build_initial_queries(
        self,
        protocol:   ReviewProtocol,
        llm_client: Any,
    ) -> List[SearchQuery]:
        """
        Parameters
        ----------
        protocol   : ReviewProtocol
        llm_client : LLMClient instance

        Returns
        -------
        List[SearchQuery]
            Single SearchQuery with pubmed_query_override and s2_query_override
            set by the LLM, or a rule-based fallback if the LLM call fails.
        """
        prompt = _build_llm_prompt(protocol)

        try:
            response = await llm_client.complete(
                prompt          = prompt,
                system          = _LLM_SYSTEM_PROMPT,
                model           = llm_client.GPT_MODEL,
                temperature     = 0.0,
                max_tokens      = 512,
                response_format = "json",
            )
        except Exception as exc:
            logger.warning(
                "LLMQueryBuilder: LLM call failed (%s) — using rule-based fallback", exc
            )
            return self._fallback.build_initial_queries(protocol)

        parsed = _parse_llm_response(response)
        if not parsed:
            logger.warning(
                "LLMQueryBuilder: could not parse LLM response — using rule-based fallback"
            )
            return self._fallback.build_initial_queries(protocol)

        pubmed_query, s2_query = parsed
        logger.info(
            "LLMQueryBuilder: pubmed='%s'  s2='%s'",
            pubmed_query[:120], s2_query[:80],
        )

        # Append year filter to PubMed query if the protocol specifies a date range
        if protocol.date_range:
            start, end = protocol.date_range
            pubmed_query += f' AND ("{start}/01/01"[PDAT]:"{end}/12/31"[PDAT])'

        base_queries = self._fallback.build_initial_queries(protocol)
        base = base_queries[0]
        return [
            base.model_copy(update={
                "pubmed_query_override": pubmed_query,
                "s2_query_override":     s2_query,
            })
        ]
