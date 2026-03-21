import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

# trivial words ignored during token overlap check
_TRIVIAL: frozenset = frozenset({
    "the", "a", "an", "of", "in", "for", "and", "or", "with",
    "to", "on", "is", "are", "was", "be", "by", "at", "its",
    "this", "that", "it", "as", "from", "into", "not", "but"
})


class DomainValidator:
    """
    Generic domain relevance checker.
    Decides whether an LLM-suggested term belongs to the research domain.

    Fully domain-agnostic — works for medicine, law, IT, or any field.
    The domain is defined entirely by:
      - vocabulary: optional known terms passed in at construction (frozenset)
      - domainKeywords: from SearchQuery, the PICO anchors
      - researchQuestion: the full research question as a text anchor

    Three level check:
      Level 0 — vocabulary frozenset (O(1) lookup, optional)
      Level 1 — substring containment against anchors
      Level 2 — word token overlap against anchors
      Level 3 — fail, term is off-topic
    """

    def __init__(self, vocabulary: frozenset = frozenset()):
        """
        vocabulary : optional frozenset of known in-domain terms.
                     Pass an empty frozenset() if you want pure dynamic validation
                     from the SearchQuery fields alone.
                     Pass a domain-specific frozenset to add a fast O(1) lookup layer
                     on top of the dynamic checks.
        """
        self.__vocabulary: frozenset = frozenset(t.lower() for t in vocabulary)

    @property
    def vocabulary(self) -> frozenset:
        return self.__vocabulary

    def isRelevant(
        self,
        term: str,
        domainKeywords: List[str],
        researchQuestion: str,
    ) -> Tuple[bool, str]:
        """
        Check whether a term belongs to the research domain.

        Returns (is_relevant: bool, reason: str)
        reason describes which level matched or why it failed.
        """
        termLower = term.lower().strip()

        # level 0 — vocabulary frozenset (exact match)
        if termLower in self.__vocabulary:
            return True, "vocabulary_exact"

        # level 0 — vocabulary frozenset (partial match)
        for vocabTerm in self.__vocabulary:
            if vocabTerm in termLower or termLower in vocabTerm:
                return True, f"vocabulary_partial:{vocabTerm}"

        # build anchor list from domainKeywords + researchQuestion
        anchors = []
        for kw in domainKeywords:
            for part in kw.split(","):
                part = part.strip().lower()
                if part:
                    anchors.append(part)
        if researchQuestion:
            anchors.append(researchQuestion.lower())

        if researchQuestion:
            anchors.append(researchQuestion.lower())

        # level 1 — substring containment
        for anchor in anchors:
            if termLower in anchor or anchor in termLower:
                return True, "substring_match"

        # level 2 — word token overlap
        termTokens = {
            w for w in termLower.split()
            if w not in _TRIVIAL and len(w) > 2
        }

        anchorTokens: set = set()
        for anchor in anchors:
            anchorTokens.update(
                w for w in anchor.split()
                if w not in _TRIVIAL and len(w) > 2
            )

        overlap = termTokens & anchorTokens
        if overlap:
            return True, f"token_overlap:{','.join(overlap)}"

        return False, "off_topic"