import time
import logging
from openai import OpenAI
from connector.BaseConnector import BaseConnector

logger = logging.getLogger(__name__)


class GptConnector(BaseConnector):
    """
    Low level LLM API wrapper.
    Knows HOW to talk to the LLM — nothing else.
    Does not know about refinement, screening, or any domain logic.

    CRITICAL — BFH MLMP constraint:
    timeout must be set on the OpenAI client constructor.
    Do NOT pass timeout= or max_tokens= to individual create() calls.
    LMStudio backend crashes with HTTP 400 / exit-code-null if you do.
    """

    def __init__(
        self,
        baseUrl: str,
        apiKey: str,
        modelName: str = "gpt-oss:120b",
        timeout: int = 120,
        maxRetries: int = 2,
        temperature: float = 0.2,
    ):
        super().__init__(apiKey=apiKey, baseUrl=baseUrl)
        self.__modelName: str = modelName
        self.__timeout: int = timeout
        self.__maxRetries: int = maxRetries
        self.__temperature: float = temperature
        self.__client = OpenAI(
            base_url=self.baseUrl,
            api_key=self.apiKey,
            timeout=self.__timeout
        )

    @property
    def modelName(self) -> str:
        return self.__modelName

    @property
    def temperature(self) -> float:
        return self.__temperature

    def callLlm(self, prompt: str, systemMessage: str) -> str:
        """
        Send one prompt to the LLM and return the raw string response.
        Retries up to maxRetries times with exponential backoff on failure.
        Returns empty string if all retries fail — never raises to caller.
        """
        for attempt in range(1, self.__maxRetries + 1):
            try:
                response = self.__client.chat.completions.create(
                    model=self.__modelName,
                    temperature=self.__temperature,
                    messages=[
                        {"role": "system", "content": systemMessage},
                        {"role": "user", "content": prompt},
                    ]
                )
                return response.choices[0].message.content.strip()

            except Exception as e:
                logger.warning(
                    "GptConnector: attempt %d/%d failed: %s",
                    attempt, self.__maxRetries, e
                )
                if attempt < self.__maxRetries:
                    time.sleep(2 ** attempt)
                else:
                    logger.error("GptConnector: all retries exhausted")
                    return ""


# DELETE BEFORE PRODUCTION — smoke test
# run: python -m module1.connectors.GptConnector
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    connector = GptConnector(
        baseUrl=os.getenv("OPENAI_BASE_URL", "https://inference.mlmp.ti.bfh.ch/api/v1"),
        apiKey=os.getenv("OPENAI_API_KEY", ""),
        modelName=os.getenv("OPENAI_MODEL", "gpt-oss:120b"),
    )

    print("Running GptConnector smoke test...")
    print("-" * 50)

    result = connector.callLlm(
        prompt="List 3 synonyms for 'systematic review'. Comma separated only.",
        systemMessage="You are a research expert. Reply only with comma-separated terms."
    )

    print(f"Response: {result}")
    print("Smoke test complete.")