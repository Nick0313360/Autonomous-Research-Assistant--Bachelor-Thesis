"""
tier1_search/deduplication.py
==============================
Deduplication of CandidateRecord lists.

Priority order:
  1. Exact DOI match   (case-insensitive, stripped)
  2. Exact PMID match  (stripped)
  3. Title similarity  ≥ 0.95 via Levenshtein ratio (case-folded, stripped)

The first record encountered for each canonical identity is kept; all
subsequent matches are marked as duplicates and logged.
"""
from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from Levenshtein import ratio as lev_ratio

from models.data_classes import CandidateRecord

logger = logging.getLogger(__name__)

_TITLE_THRESHOLD = 0.95
_DEDUP_STATUS_UNIQUE = "unique"
_DEDUP_STATUS_DUPLICATE = "duplicate"


def _normalise_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d or None


def _normalise_pmid(pmid: Optional[str]) -> Optional[str]:
    if not pmid:
        return None
    return pmid.strip() or None


def _normalise_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


class DeduplicationEngine:
    """
    Stateless deduplication engine.

    All duplicate pairs are recorded and available via ``duplicate_pairs``
    after each ``deduplicate`` call.
    """

    def __init__(self) -> None:
        self.duplicate_pairs: List[Tuple[str, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def deduplicate(self, records: List[CandidateRecord]) -> List[CandidateRecord]:
        """
        Return deduplicated records (earliest occurrence kept).

        Side-effects:
          - ``self.duplicate_pairs`` is reset and then populated with
            (kept_record_id, duplicate_record_id) pairs.
          - Each returned record has ``deduplication_status`` set to
            ``"unique"``.  Dropped duplicates are not returned but are
            logged at DEBUG level.
        """
        self.duplicate_pairs = []

        doi_index:   Dict[str, str] = {}   # normalised_doi   → kept record_id
        pmid_index:  Dict[str, str] = {}   # normalised_pmid  → kept record_id
        title_index: Dict[str, str] = {}   # normalised_title → kept record_id

        kept: List[CandidateRecord] = []

        for rec in records:
            canonical_id = self._find_duplicate(
                rec, doi_index, pmid_index, title_index
            )
            if canonical_id is not None:
                self.duplicate_pairs.append((canonical_id, rec.record_id))
                logger.debug(
                    "Duplicate: %r (%s) → canonical %s",
                    rec.title[:60],
                    rec.record_id,
                    canonical_id,
                )
                continue

            # First occurrence — register and keep
            self._register(rec, doi_index, pmid_index, title_index)
            kept.append(replace(rec, deduplication_status=_DEDUP_STATUS_UNIQUE))

        logger.info(
            "Deduplication: %d in → %d unique, %d duplicates removed",
            len(records),
            len(kept),
            len(self.duplicate_pairs),
        )
        return kept

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_duplicate(
        self,
        rec: CandidateRecord,
        doi_index:   Dict[str, str],
        pmid_index:  Dict[str, str],
        title_index: Dict[str, str],
    ) -> Optional[str]:
        """Return the kept record_id if *rec* is a duplicate, else None."""

        # 1. DOI
        ndoi = _normalise_doi(rec.doi)
        if ndoi and ndoi in doi_index:
            return doi_index[ndoi]

        # 2. PMID
        npmid = _normalise_pmid(rec.pmid)
        if npmid and npmid in pmid_index:
            return pmid_index[npmid]

        # 3. Title similarity
        ntitle = _normalise_title(rec.title)
        for indexed_title, rid in title_index.items():
            if lev_ratio(ntitle, indexed_title) >= _TITLE_THRESHOLD:
                return rid

        return None

    @staticmethod
    def _register(
        rec: CandidateRecord,
        doi_index:   Dict[str, str],
        pmid_index:  Dict[str, str],
        title_index: Dict[str, str],
    ) -> None:
        ndoi   = _normalise_doi(rec.doi)
        npmid  = _normalise_pmid(rec.pmid)
        ntitle = _normalise_title(rec.title)

        if ndoi:
            doi_index[ndoi]     = rec.record_id
        if npmid:
            pmid_index[npmid]   = rec.record_id
        title_index[ntitle]     = rec.record_id
