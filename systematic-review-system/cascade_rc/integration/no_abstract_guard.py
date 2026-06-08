from enum import Enum
from dataclasses import dataclass


class AbstractStatus(Enum):
    ORIGINAL = "original"
    ENTREZ_RECOVERED = "entrez_recovered"
    TITLE_ONLY = "title_only"
    UNAVAILABLE = "unavailable"


def requires_human_review_due_to_no_abstract(abstract_source: str) -> bool:
    """
    Returns True for PMIDs that must be routed directly to human_review
    BEFORE the cascade runs, bypassing s/u scoring entirely.
    Only "unavailable" triggers this — title_only and entrez_recovered
    have enough text for LLM scoring.
    """
    return abstract_source == AbstractStatus.UNAVAILABLE.value


def get_abstract_source(parquet_row: dict) -> str:
    """
    Safe accessor for abstract_source column.
    Returns "original" if column is absent (backward compatibility).
    """
    return parquet_row.get("abstract_source", "original")
