from .abstract_screener import AbstractScreener
from .fulltext_screener import FullTextScreener
from .decision_engine import DecisionEngine
from .pico_extractor import PICOExtractor


def __getattr__(name: str):  # type: ignore[return]
    """Lazy-load HybridRetriever (requires faiss/torch) only when accessed."""
    if name == "HybridRetriever":
        from .hybrid_retriever import HybridRetriever
        return HybridRetriever
    raise AttributeError(f"module 'tier2_screening' has no attribute {name!r}")
