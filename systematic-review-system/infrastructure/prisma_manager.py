"""
infrastructure/prisma_manager.py
================================
Thread-safe PRISMA 2020 flow tracker for a single systematic review run.

The manager owns one PRISMAState instance and provides named update methods
that mirror the PRISMA 2020 flow diagram stages.  All mutations are protected
by a threading.Lock so concurrent pipeline stages can update safely.

PRISMA 2020 stage mapping
--------------------------
Identification
  record_identification(count)      → identification_total
  record_deduplication(removed)     → duplicates_removed, after_dedup

Screening
  record_abstract_screening(inc, exc)   → abstracts_screened, abstract_excluded, abstract_included
  record_fulltext_retrieval(ret, failed) → fulltext_sought, fulltext_not_retrieved
  record_fulltext_screening(inc, exc, reasons) → fulltext_assessed, fulltext_excluded, fulltext_included

Included
  record_inclusion(count)           → studies_included
"""
from __future__ import annotations

import logging
import threading
from typing import Dict

from models.data_classes import PRISMAState

logger = logging.getLogger(__name__)

# Keys written into PRISMAState.stage_counts — kept as constants so callers
# can reference them without magic strings.
K_IDENTIFIED          = "identification_total"
K_DUPLICATES_REMOVED  = "duplicates_removed"
K_AFTER_DEDUP         = "after_dedup"
K_ABSTRACTS_SCREENED  = "abstracts_screened"
K_ABSTRACT_EXCLUDED   = "abstract_excluded"
K_ABSTRACT_INCLUDED   = "abstract_included"
K_FULLTEXT_SOUGHT     = "fulltext_sought"
K_FULLTEXT_NOT_RETR   = "fulltext_not_retrieved"
K_FULLTEXT_ASSESSED   = "fulltext_assessed"
K_FULLTEXT_EXCLUDED   = "fulltext_excluded"
K_FULLTEXT_INCLUDED   = "fulltext_included"
K_STUDIES_INCLUDED    = "studies_included"


class PRISMAManager:
    """
    Singleton per review_id that accumulates PRISMA 2020 flow counts.

    Parameters
    ----------
    review_id : str
        Identifies the review.  Also stored in the underlying PRISMAState.
    """

    def __init__(self, review_id: str) -> None:
        self._lock  = threading.Lock()
        self._state = PRISMAState(review_id=review_id)
        logger.info("PRISMAManager initialised for review %s", review_id)

    # ------------------------------------------------------------------
    # State update methods
    # ------------------------------------------------------------------

    def record_identification(self, count: int) -> None:
        """Records identified from database searches (before deduplication)."""
        with self._lock:
            self._state.stage_counts[K_IDENTIFIED] = (
                self._state.stage_counts.get(K_IDENTIFIED, 0) + count
            )

    def record_deduplication(self, removed: int) -> None:
        """Records how many duplicates were removed."""
        with self._lock:
            identified = self._state.stage_counts.get(K_IDENTIFIED, 0)
            self._state.stage_counts[K_DUPLICATES_REMOVED] = (
                self._state.stage_counts.get(K_DUPLICATES_REMOVED, 0) + removed
            )
            self._state.stage_counts[K_AFTER_DEDUP] = max(
                0, identified - self._state.stage_counts[K_DUPLICATES_REMOVED]
            )

    def record_abstract_screening(self, included: int, excluded: int) -> None:
        """Records abstract-level screening outcomes."""
        with self._lock:
            screened = included + excluded
            self._state.stage_counts[K_ABSTRACTS_SCREENED] = (
                self._state.stage_counts.get(K_ABSTRACTS_SCREENED, 0) + screened
            )
            self._state.stage_counts[K_ABSTRACT_EXCLUDED] = (
                self._state.stage_counts.get(K_ABSTRACT_EXCLUDED, 0) + excluded
            )
            self._state.stage_counts[K_ABSTRACT_INCLUDED] = (
                self._state.stage_counts.get(K_ABSTRACT_INCLUDED, 0) + included
            )

    def record_fulltext_retrieval(self, retrieved: int, failed: int) -> None:
        """Records how many full-texts were sought and how many could not be retrieved."""
        with self._lock:
            self._state.stage_counts[K_FULLTEXT_SOUGHT] = (
                self._state.stage_counts.get(K_FULLTEXT_SOUGHT, 0) + retrieved + failed
            )
            self._state.stage_counts[K_FULLTEXT_NOT_RETR] = (
                self._state.stage_counts.get(K_FULLTEXT_NOT_RETR, 0) + failed
            )

    def record_fulltext_screening(
        self,
        included: int,
        excluded: int,
        reasons_dict: Dict[str, int],
    ) -> None:
        """
        Records full-text screening outcomes.

        Parameters
        ----------
        included : int
            Papers that passed full-text screening.
        excluded : int
            Papers excluded at full-text stage.
        reasons_dict : dict[str, int]
            Mapping of exclusion reason → count.  Merged cumulatively into
            PRISMAState.exclusion_reasons.
        """
        with self._lock:
            assessed = included + excluded
            self._state.stage_counts[K_FULLTEXT_ASSESSED] = (
                self._state.stage_counts.get(K_FULLTEXT_ASSESSED, 0) + assessed
            )
            self._state.stage_counts[K_FULLTEXT_EXCLUDED] = (
                self._state.stage_counts.get(K_FULLTEXT_EXCLUDED, 0) + excluded
            )
            self._state.stage_counts[K_FULLTEXT_INCLUDED] = (
                self._state.stage_counts.get(K_FULLTEXT_INCLUDED, 0) + included
            )
            for reason, cnt in reasons_dict.items():
                self._state.exclusion_reasons[reason] = (
                    self._state.exclusion_reasons.get(reason, 0) + cnt
                )

    def record_inclusion(self, count: int) -> None:
        """Records final studies included in the review."""
        with self._lock:
            self._state.stage_counts[K_STUDIES_INCLUDED] = (
                self._state.stage_counts.get(K_STUDIES_INCLUDED, 0) + count
            )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def generate_prisma_counts(self) -> dict:
        """
        Return a flat dict with all PRISMA 2020 required counts.

        Keys follow PRISMA 2020 terminology and can be used directly in
        report templates or PRISMA flow-diagram renderers.
        Missing counts default to 0 so the dict is always complete.
        """
        with self._lock:
            sc = dict(self._state.stage_counts)
            er = dict(self._state.exclusion_reasons)

        return {
            # Identification
            "records_identified":          sc.get(K_IDENTIFIED,         0),
            "duplicates_removed":          sc.get(K_DUPLICATES_REMOVED, 0),
            "records_after_deduplication": sc.get(K_AFTER_DEDUP,        0),
            # Screening
            "records_screened":            sc.get(K_ABSTRACTS_SCREENED, 0),
            "records_excluded_abstract":   sc.get(K_ABSTRACT_EXCLUDED,  0),
            "records_sought_fulltext":     sc.get(K_FULLTEXT_SOUGHT,    0),
            "records_not_retrieved":       sc.get(K_FULLTEXT_NOT_RETR,  0),
            "records_assessed_fulltext":   sc.get(K_FULLTEXT_ASSESSED,  0),
            "records_excluded_fulltext":   sc.get(K_FULLTEXT_EXCLUDED,  0),
            # Included
            "studies_included":            sc.get(K_STUDIES_INCLUDED,   0),
            # Supplementary
            "exclusion_reasons":           er,
            "query_versions":              list(self._state.query_versions),
        }

    # ------------------------------------------------------------------
    # Direct state access (read-only snapshot)
    # ------------------------------------------------------------------

    @property
    def state(self) -> PRISMAState:
        """Return a shallow copy of the current PRISMAState (thread-safe read)."""
        with self._lock:
            from dataclasses import replace
            return replace(
                self._state,
                stage_counts      = dict(self._state.stage_counts),
                exclusion_reasons = dict(self._state.exclusion_reasons),
                query_versions    = list(self._state.query_versions),
            )

    def add_query_version(self, version: str) -> None:
        """Track a new query string/version used during retrieval."""
        with self._lock:
            self._state.query_versions.append(version)
