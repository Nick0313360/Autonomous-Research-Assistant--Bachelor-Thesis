"""
cascade_rc/tests/test_async_ensemble.py
========================================
Benchmark: verify async ensemble is ≥10× faster than the sequential baseline.

Run with:
    pytest cascade_rc/tests/test_async_ensemble.py -v -s
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from infrastructure.llm_client import LLMResponse
from cascade_rc.cache.llm_ensemble import score_topic_async


# ---------------------------------------------------------------------------
# Test parameters
# ---------------------------------------------------------------------------

CALL_LATENCY = 0.05   # 50 ms synthetic LLM latency per call
N_PMIDS = 100
B = 5
N_CONCURRENT = 20

# Sequential baseline: N_PMIDS × B × CALL_LATENCY = 100 × 5 × 0.05 = 25 s
# Async expected: (N_PMIDS / N_CONCURRENT) × CALL_LATENCY = 5 × 0.05 = 0.25 s
# Required speedup: ≥10× (i.e. elapsed < 2.5 s with generous asyncio overhead)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "pmid":     [str(i) for i in range(n)],
        "title":    [f"Title {i}" for i in range(n)],
        "abstract": [f"Abstract text for study number {i}." for i in range(n)],
    })


def _make_mock_cache() -> MagicMock:
    cache = MagicMock()
    cache.get.return_value = None          # force all cache misses
    cache.put.return_value = None
    cache.stats.return_value = {
        "total_rows": 0,
        "unique_pmids": 0,
        "rows_per_seed_b": {},
    }
    return cache


def _mock_llm_response() -> LLMResponse:
    return LLMResponse(
        content='{"satisfies": true}',
        model_used="mock",
        input_tokens=50,
        output_tokens=5,
        latency_ms=CALL_LATENCY * 1000,
        parsed_json={"satisfies": True},
    )


# ---------------------------------------------------------------------------
# Benchmark test
# ---------------------------------------------------------------------------

def test_async_speedup_vs_sequential() -> None:
    """Async ensemble must be ≥10× faster than the sequential PMID-loop baseline."""
    pico = {
        "population":   "adults with suspected condition",
        "intervention": "index test",
        "comparator":   "reference standard",
        "outcome":      "diagnostic accuracy",
        "study_design": "cross-sectional",
    }
    df = _make_df(N_PMIDS)
    cache = _make_mock_cache()

    async def mock_complete(self: Any, **kwargs: Any) -> LLMResponse:
        """Simulate network latency without actually calling the API."""
        await asyncio.sleep(CALL_LATENCY)
        return _mock_llm_response()

    with patch("infrastructure.llm_client.LLMClient.complete", mock_complete):
        start = time.monotonic()
        stats = asyncio.run(
            score_topic_async(
                df=df,
                pico=pico,
                model_id="mock-model",
                temperature=0.7,
                B=B,
                cache=cache,
                n_concurrent=N_CONCURRENT,
                template_v="v1",
            )
        )
        elapsed = time.monotonic() - start

    sequential_baseline_s = N_PMIDS * B * CALL_LATENCY  # 25 s
    speedup = sequential_baseline_s / elapsed

    # Correctness assertions
    assert not stats["aborted"], "Run should complete without abort"
    assert stats["processed"] == N_PMIDS, (
        f"Expected {N_PMIDS} PMIDs processed, got {stats['processed']}"
    )

    # Speed assertion: must be ≥10× faster than sequential
    assert elapsed < sequential_baseline_s / 10, (
        f"Async took {elapsed:.2f}s; sequential baseline = {sequential_baseline_s:.2f}s. "
        f"Achieved speedup = {speedup:.1f}× — expected ≥10×.\n"
        f"  Check that asyncio.gather inside screen_abstract_ensemble is not blocked."
    )

    print(
        f"\n[BENCHMARK] {N_PMIDS} PMIDs × B={B} seeds | concurrency={N_CONCURRENT}\n"
        f"  elapsed = {elapsed:.2f}s\n"
        f"  speedup = {speedup:.1f}× vs sequential ({sequential_baseline_s:.1f}s baseline)\n"
        f"  rate    = {stats['rate_pmids_per_min']:.0f} PMIDs/min\n"
        f"  (production target: ≥960 PMIDs/min with real 6.1 s LLM latency)"
    )


# ---------------------------------------------------------------------------
# Smoke: ensure cache hits short-circuit LLM calls
# ---------------------------------------------------------------------------

def test_cache_hits_skip_llm() -> None:
    """When all B slots are cached, no LLM calls should be made."""
    from cascade_rc.cache.llm_ensemble import _vote_to_int

    df = _make_df(5)
    pico = {k: "test" for k in ("population", "intervention", "comparator", "outcome", "study_design")}

    # Return a fully-cached ensemble for every get() call
    cached_row = {"vote_label": "Include", "verdict": 1, "response": {"satisfies": True}}
    cache = _make_mock_cache()
    cache.get.return_value = cached_row  # every slot is a hit

    call_count = 0

    async def mock_complete(self: Any, **kwargs: Any) -> LLMResponse:
        nonlocal call_count
        call_count += 1
        return _mock_llm_response()

    with patch("infrastructure.llm_client.LLMClient.complete", mock_complete):
        asyncio.run(
            score_topic_async(
                df=df,
                pico=pico,
                model_id="mock-model",
                temperature=0.7,
                B=B,
                cache=cache,
                n_concurrent=N_CONCURRENT,
                template_v="v1",
            )
        )

    assert call_count == 0, (
        f"Expected 0 LLM calls (all cache hits), but got {call_count}"
    )
