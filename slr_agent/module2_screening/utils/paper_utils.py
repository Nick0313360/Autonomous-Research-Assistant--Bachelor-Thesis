"""
Paper identification and validation utilities.
"""

import hashlib
from typing import Any


def make_paper_id_static(paper) -> str:
    """
    Generate a stable string ID for a paper.
    Uses DOI if present, otherwise hash of title+abstract.
    """
    if paper.doi:
        return paper.doi.strip().lower().replace("/", "_")
    
    raw = (paper.title + paper.abstract).encode("utf-8")
    return "hash_" + hashlib.sha256(raw).hexdigest()[:16]


# Alias for backward compatibility
_makePaperIdStatic = make_paper_id_static


def validate_pico_fields(query) -> bool:
    """
    Validate that required PICO fields are present.
    """
    return bool(
        query.researchQuestion 
        and query.population 
        and query.intervention
    )