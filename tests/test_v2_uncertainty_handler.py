import numpy as np
from slr_agent.module2_screening_v2.layers import (
    UncertaintyHandler,
    PromptBuilder,
    ExampleBuffer,
)
from slr_agent.module2_screening_v2.models import ScreeningConfig, ResolvedResult
from slr_agent.module2_screening_v2.layers import RealPrimaryScreener
from slr_agent.module2_screening_v2.layers import LLMClient
from slr_agent.module2_screening.models import Paper, RankedPaper, ScreeningResult


class DummyLLM:
    async def completeAsync(self, prompt, system, temperature=0.0):
        # Return an INCLUDE decision for testing
        return '{"decision":"INCLUDE","confidence":0.9,"reasoning":"test"}'


class DummyPromptBuilder:
    def buildCotPrompt(self, picoText, title, abstract, examples):
        system = "system"
        user = "user"
        return system, user


def _make_paper(title: str, abstract: str) -> Paper:
    return Paper(title=title, abstract=abstract, doi=None, year=None, source="test")


def _make_ranked(
    paper: Paper, embedding: np.ndarray, sim: float, pid: str
) -> RankedPaper:
    return RankedPaper(paper=paper, embedding=embedding, simScore=sim, paperId=pid)


def test_uncertainty_handler_resolves_and_updates_prisma(monkeypatch):
    # Seed ExampleBuffer with one example so getSimilar() has content
    from slr_agent.module2_screening_v2.layers import ExampleBuffer as V2ExampleBuffer

    buf = V2ExampleBuffer(
        seed_examples=[
            {
                "embedding": np.zeros(768),
                "title": "Seed Paper",
                "abstract": "seed abstract",
                "decision": "include",
                "reasoning": "seed",
            }
        ]
    )

    # Create a single uncertain paper
    paper = _make_paper("Uncertain Paper", "An abstract about something uncertain.")
    rp = RankedPaper(paper=paper, embedding=np.zeros(768), simScore=0.4, paperId="up1")
    sr = ScreeningResult(
        rankedPaper=rp,
        decision="UNCERTAIN",
        confidence=0.5,
        rawResponse="",
        method="llm_primary",
    )

    mock_llm = type(
        "M",
        (),
        {
            "completeAsync": lambda *a, **k: (
                '{"decision":"INCLUDE","confidence":0.9,"reasoning":"ok"}'
            )
        },
    )
    # But we want async so wrap with a coroutine: create an async function
    import types

    class AsyncMock:
        async def completeAsync(self, prompt, system, temperature=0.0):
            return '{"decision":"INCLUDE","confidence":0.9,"reasoning":"ok"}'

    llm = AsyncMock()
    pb = DummyPromptBuilder()
    uhandler = UncertaintyHandler(
        llmClient=llm, promptBuilder=pb, exampleBuffer=buf, concurrency=5
    )
    results = uhandler.resolve(
        [sr], pico_text="Population: P Intervention: I Outcome: O", emitLog=None
    )
    # results should be a list with one ResolvedResult
    assert isinstance(results, list) and len(results) == 1
    rr = results[0]
    assert isinstance(rr, ResolvedResult)  # type: ignore
    assert rr.finalDecision in ("INCLUDE", "EXCLUDE")
    # Prisma should be updated
    from slr_agent.module2_screening_v2.prisma_log import PrismaLog

    p = PrismaLog.getInstance()
    assert hasattr(p, "v2_uncertainToLLM2")
    assert p.v2_uncertainToLLM2 >= 1
