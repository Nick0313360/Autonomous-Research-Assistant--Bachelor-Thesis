"""
Text processing utilities for abstracts and strings.
"""


def truncate_abstract(abstract: str, max_length: int = 500) -> str:
    """
    Truncate abstract to specified length with ellipsis if needed.
    """
    if len(abstract) <= max_length:
        return abstract
    return abstract[:max_length] + "..."