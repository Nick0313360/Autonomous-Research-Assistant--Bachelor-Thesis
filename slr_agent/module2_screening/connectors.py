"""Module 2 — Connectors (LLM)"""

from __future__ import annotations
from typing import Optional


class GptConnector:
    """Module 1::Connector::GptConnector — reused verbatim."""

    def __init__(self, modelName: str = "claude-haiku-4-5-20251001", baseUrl: str = ""):
        self.modelName = modelName
        self.baseUrl = baseUrl
        self.timeout = 30
        self.maxRetries = 3

    def call_llm(
        self, prompt: str, systemMessage: str, temperature: float = 0.0
    ) -> str:
        import anthropic

        client = anthropic.Anthropic()
        for attempt in range(self.maxRetries):
            try:
                response = client.messages.create(
                    model=self.modelName,
                    max_tokens=1000,
                    system=systemMessage,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except Exception as exc:
                if attempt == self.maxRetries - 1:
                    raise RuntimeError(
                        f"GptConnector failed after {self.maxRetries} retries: {exc}"
                    ) from exc
        return ""
