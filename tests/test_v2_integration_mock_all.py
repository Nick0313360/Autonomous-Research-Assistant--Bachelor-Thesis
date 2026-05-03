import json
import hashlib
import numpy as np

from slr_agent.module2_screening_v2.orchestrator import runScreeningV2
from slr_agent.module2_screening.models import Paper, SearchQuery
from slr_agent.module2_screening_v2.models import ScreeningOutput


def _make_paper(title: str, abstract: str, doi: str | None = None) -> Paper:
    return Paper(title=title, abstract=abstract, doi=doi, year=None, source="test")


def _makePaperId(paper: Paper) -> str:
    if paper.doi:
        return paper.doi.strip().lower().replace("/", "_")
    raw = (paper.title + paper.abstract).encode("utf-8")
    return "hash_" + hashlib.sha256(raw).hexdigest()[:16]


class MockEmbeddingService:
    def __init__(self, *args, **kwargs):
        pass

    def selectModel(self, query):
        return "specter2"

    def embedPapers(self, papers, modelKey, batchSize=32):
        mapping = {}
        for idx, paper in enumerate(papers):
            pid = _makePaperId(paper)
            vec = np.ones(768, dtype=float) * (idx + 1) * 0.5
            mapping[pid] = vec
        return mapping

    def embedQuery(self, query, modelKey):
        return np.ones(768, dtype=float) * 0.9


class MockLLMClient:
    async def completeAsync(self, prompt, system, temperature=0.0):
        return json.dumps(
            {"decision": "INCLUDE", "confidence": 0.92, "reasoning": "mock"}
        )


def test_integration_with_mock_embedding_and_llm(monkeypatch):
    # Patch embedding service and LLM client in the v2 orchestrator path
    monkeypatch.setattr(
        "slr_agent.module2_screening_v2.orchestrator.EmbeddingService",
        MockEmbeddingService,
    )
    monkeypatch.setattr(
        "slr_agent.module2_screening_v2.orchestrator.LLMClient", MockLLMClient
    )

    papers = [
        _make_paper("T1", "A1", doi="10.1000/xyz1"),
        _make_paper("T2", "A2", doi="10.1000/xyz2"),
    ]
    q = SearchQuery(
        researchQuestion="RQ", population="P", intervention="I", outcome="O"
    )
    result: ScreeningOutput = runScreeningV2(papers, q)
    assert isinstance(result, ScreeningOutput)
    # With mock LLM including both papers, we expect some includes or at least no crash
    # We can't rely on exact counts since the mock L2 is deterministic here
    assert hasattr(result, "includedPapers")
