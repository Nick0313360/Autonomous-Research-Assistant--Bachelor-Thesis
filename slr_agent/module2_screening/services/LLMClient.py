import asyncio
import concurrent.futures
import time
import logging

from module1.connector.GptConnector import GptConnector

class LLMClient:
    """
    Module 2::Support::LLMClient  (NEW — add to class diagram)

    Wraps GptConnector.call_llm() with:
      - Async-compatible execution (blocking call offloaded to ThreadPoolExecutor)
      - Exponential backoff on transient failures (429, 500, 503)
      - Configurable model name and max_tokens per client instance

    Separation of concerns: PrimaryScreener and UncertaintyHandler depend on
    LLMClient, not directly on GptConnector. This makes both layers independently
    testable by injecting a mock LLMClient.

    Attributes:
      _connector   — GptConnector; owns the actual Anthropic SDK call
      _executor    — ThreadPoolExecutor; bridges blocking call_llm into asyncio
      _maxRetries  — int; how many times to retry on transient API errors
      _backoffBase — float; base seconds for exponential backoff (default 1.0)
    """

    def __init__(
        self,
        modelName:   str = "claude-haiku-4-5-20251001",
        maxRetries:  int = 3,
        backoffBase: float = 1.0,
    ):
        """
        Initialise the LLM client.

        Args:
          modelName:   Anthropic model string. Haiku for L2, Sonnet for L3.
          maxRetries:  Retry count on transient errors before raising.
          backoffBase: Base delay in seconds. Retry N uses backoffBase * 2^N.
        """
        self._connector  = GptConnector(modelName=modelName)
        self._executor   = concurrent.futures.ThreadPoolExecutor(max_workers=30)
        self._maxRetries = maxRetries
        self._backoffBase = backoffBase

    def completeSync(self, prompt: str, system: str, temperature: float = 0.0) -> str:
        """
        Synchronous completion. Retries with exponential backoff on failure.

        Args:
          prompt:      User-turn content.
          system:      System prompt content.
          temperature: Sampling temperature. Use 0.0 for determinism.

        Returns:
          Raw text response from the model.

        Raises:
          RuntimeError: If all retries are exhausted.
        """
        for attempt in range(self._maxRetries):
            try:
                return self._connector.call_llm(prompt, system, temperature)
            except Exception as exc:
                if attempt == self._maxRetries - 1:
                    raise RuntimeError(
                        f"LLMClient: exhausted {self._maxRetries} retries — {exc}"
                    ) from exc
                wait = self._backoffBase * (2 ** attempt)
                log.warning("LLMClient: retry %d/%d after %.1fs — %s",
                            attempt + 1, self._maxRetries, wait, exc)
                time.sleep(wait)
        return ""

    async def completeAsync(
        self,
        prompt: str,
        system: str,
        temperature: float = 0.0,
    ) -> str:
        """
        Async-compatible completion. Runs completeSync in a thread pool so
        the event loop is not blocked.

        Args:
          prompt:      User-turn content.
          system:      System prompt content.
          temperature: Sampling temperature.

        Returns:
          Raw text response from the model.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self.completeSync,
            prompt,
            system,
            temperature,
        )
