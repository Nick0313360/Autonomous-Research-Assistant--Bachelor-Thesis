"""
deduplicator.py — Paper Deduplication
=======================================
Design Concepts
---------------
1. Two-Phase Deduplication (DOI → Fuzzy Title)
   Phase 1 is O(n) using a hash set on normalised DOIs.
   Phase 2 is O(n²) fuzzy matching using rapidfuzz.fuzz.ratio.
   Separating the phases keeps the fast path fast.

2. Source Preference
   When a DOI duplicate is found, we keep the copy from whichever source
   has more metadata (abstract present). Previously the first-seen copy was
   always kept regardless of completeness.

3. Structured Stats
   The returned stats dict is extended with a 'total_removed' key so callers
   can compute reduction ratios without doing arithmetic themselves.
"""

import logging
from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


def deduplicate(papers: list, similarity_threshold: int = 90) -> tuple[list, dict]:
    """
    Remove duplicate papers from a combined list.

    Parameters
    ----------
    papers               : List of paper dicts (title, doi, abstract, …).
    similarity_threshold : Fuzzy title match score [0–100] above which two
                           papers are considered duplicates. Default 90.

    Returns
    -------
    (unique_papers, stats_dict)

    stats_dict keys:
        doi_duplicates   : Number removed by DOI match.
        title_duplicates : Number removed by fuzzy title match.
        total_removed    : doi_duplicates + title_duplicates.
        input_count      : Number of papers before deduplication.
        output_count     : Number of papers after deduplication.
    """
    input_count    = len(papers)
    doi_duplicates = 0
    title_duplicates = 0

    # ── Phase 1: DOI deduplication ───────────────────────────────────────────
    seen_doi: dict = {}     # doi → best paper dict (prefer one with abstract)
    no_doi: list   = []

    for p in papers:
        doi = _normalise_doi(p.get("doi"))
        if doi is None:
            no_doi.append(p)
            continue

        if doi in seen_doi:
            doi_duplicates += 1
            # Keep the copy with more metadata
            if not seen_doi[doi].get("abstract") and p.get("abstract"):
                seen_doi[doi] = p
        else:
            seen_doi[doi] = p

    after_doi = list(seen_doi.values()) + no_doi

    # ── Phase 2: Fuzzy title deduplication ──────────────────────────────────
    final: list = []

    for p in after_doi:
        title_p = p.get("title", "").lower().strip()
        if not title_p:
            final.append(p)   # can't compare, keep it
            continue

        is_duplicate = False
        for existing in final:
            score = fuzz.ratio(title_p, existing.get("title", "").lower().strip())
            if score >= similarity_threshold:
                is_duplicate = True
                title_duplicates += 1
                # Again prefer the copy with an abstract
                if not existing.get("abstract") and p.get("abstract"):
                    final[final.index(existing)] = p
                break

        if not is_duplicate:
            final.append(p)

    stats = {
        "doi_duplicates":   doi_duplicates,
        "title_duplicates": title_duplicates,
        "total_removed":    doi_duplicates + title_duplicates,
        "input_count":      input_count,
        "output_count":     len(final),
    }

    logger.info(
        "Dedup: %d in → %d out (DOI dupes: %d, title dupes: %d)",
        input_count, len(final), doi_duplicates, title_duplicates
    )
    return final, stats


def _normalise_doi(doi: str | None) -> str | None:
    """
    Normalise a DOI to lowercase stripped form for reliable comparison.
    Returns None if the DOI is absent or empty.
    """
    if not doi:
        return None
    normalised = doi.strip().lower()
    # Strip common prefixes that sometimes appear
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalised.startswith(prefix):
            normalised = normalised[len(prefix):]
    return normalised if normalised else None
