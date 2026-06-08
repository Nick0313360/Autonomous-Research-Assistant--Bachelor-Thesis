"""
infrastructure/llm_client.py
============================
Single gateway for all LLM calls in the systematic review system.

All calls route to gpt:oss120b via the BFH inference server
(OpenAI-compatible endpoint at https://inference.mlmp.ti.bfh.ch/api/v1).

Usage:
    client = LLMClient()
    response = await client.complete(prompt="...", system="...")
    responses = await client.complete_batch(prompts=[...], system="...", model=LLMClient.GPT_MODEL)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BASE_DELAY_S = 1.0  # exponential base: 1 s → 2 s → 4 s


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    content: Optional[str]          # raw text from the model
    model_used: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    parsed_json: Optional[Any] = field(default=None)   # set when response_format="json"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    """Async LLM client with retry, logging, and optional JSON parsing."""

    GPT_MODEL = "gpt-oss:120b"

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=30),
            timeout=httpx.Timeout(60.0),
        )
        self._openai = AsyncOpenAI(
            base_url=os.getenv(
                "OPENAI_BASE_URL",
                "https://inference.mlmp.ti.bfh.ch/api/v1",
            ),
            api_key=os.getenv("OPENAI_API_KEY", "no-key"),
            http_client=self._http,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(
        self,
        prompt: str,
        system: str,
        model: str = GPT_MODEL,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: str = "json",
    ) -> LLMResponse:
        """
        Call one LLM with retry logic on rate-limit / server errors.

        Args:
            prompt:          User message.
            system:          System prompt.
            model:           Model name — must be LLMClient.GPT_MODEL.
            temperature:     Sampling temperature (default 0.0 for determinism).
            max_tokens:      Maximum tokens in the completion.
            response_format: "json" (attempt to parse) or "text" (return raw).

        Returns:
            LLMResponse with content, token counts, latency, and parsed_json.
        """
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return await self._dispatch(
                    prompt, system, model, temperature, max_tokens, response_format
                )
            except Exception as exc:  # noqa: BLE001
                if _is_retryable(exc):
                    last_exc = exc
                    delay = _BASE_DELAY_S * (2 ** attempt)
                    print(
                        f"[LLMClient] retry {attempt + 1}/{_MAX_RETRIES} "
                        f"in {delay:.1f}s — {type(exc).__name__}: {exc}"
                    )
                    if attempt < _MAX_RETRIES - 1:
                        await asyncio.sleep(delay)
                else:
                    raise

        raise last_exc  # type: ignore[misc]  — only reached if all retries fail

    async def complete_batch(
        self,
        prompts: List[str],
        system: str,
        model: str,
        max_concurrency: int = 25,
    ) -> List[LLMResponse]:
        """
        Run a list of prompts concurrently, bounded by max_concurrency.

        Each prompt uses the same system prompt and model. Errors in individual
        calls propagate and cancel the gather — handle at call site if partial
        results are acceptable.
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _bounded(prompt: str) -> LLMResponse:
            async with semaphore:
                return await self.complete(
                    prompt=prompt,
                    system=system,
                    model=model,
                )

        return list(await asyncio.gather(*[_bounded(p) for p in prompts]))

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        prompt: str,
        system: str,
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: str,
    ) -> LLMResponse:
        t0 = time.monotonic()

        if model != self.GPT_MODEL:
            raise ValueError(
                f"LLMClient: unsupported model {model!r}. "
                f"Only {self.GPT_MODEL!r} (BFH inference) is permitted."
            )
        content, input_tokens, output_tokens = await self._call_openai(
            prompt, system, model, temperature, max_tokens
        )

        latency_ms = (time.monotonic() - t0) * 1000

        print(
            f"[LLMClient] model={model} "
            f"in={input_tokens} out={output_tokens} "
            f"latency={latency_ms:.0f}ms"
        )

        parsed = _safe_parse_json(content) if response_format == "json" else None

        return LLMResponse(
            content=content,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            parsed_json=parsed,
        )

    async def _call_openai(
        self,
        prompt: str,
        system: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        response = await self._openai.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        return content, input_tokens, output_tokens


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_retryable(exc: Exception) -> bool:
    """Return True for rate-limit and transient server errors."""
    if isinstance(exc, OpenAIRateLimitError):
        return True
    if (
        hasattr(exc, "status_code")
        and isinstance(getattr(exc, "status_code", None), int)
        and exc.status_code >= 500  # type: ignore[attr-defined]
    ):
        return True
    return False


def _safe_parse_json(text: str) -> Optional[Any]:
    """
    Try to parse JSON from the model's text output.

    Attempts (in order):
      1. Raw parse of the full text.
      2. Parse after stripping Markdown triple-backtick fences.
      3. Return None on failure — never raises.
    """
    if not text:
        return None

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract from ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    return None


# ---------------------------------------------------------------------------
# Smoke test (python -m infrastructure.llm_client)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO)

    async def _smoke() -> None:
        client = LLMClient()
        model = os.getenv("SMOKE_MODEL", LLMClient.GPT_MODEL)
        print(f"Smoke-testing with model: {model}")

        try:
            resp = await client.complete(
                prompt='Return JSON: {"synonyms": ["systematic review", "literature review"]}',
                system="You are a research expert. Reply only with valid JSON.",
                model=model,
                max_tokens=64,
            )
            print(f"content    : {resp.content}")
            print(f"parsed_json: {resp.parsed_json}")
            print(f"tokens     : in={resp.input_tokens} out={resp.output_tokens}")
            print(f"latency    : {resp.latency_ms:.0f}ms")
        finally:
            await client.aclose()

    asyncio.run(_smoke())
