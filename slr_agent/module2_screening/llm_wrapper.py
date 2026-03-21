import re
import os
import logging
import time
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(
    base_url=os.getenv("API_URL", "https://inference.mlmp.ti.bfh.ch/api/v1"),
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=int(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
)

log = logging.getLogger(__name__)
MODEL = os.getenv("SCREENING_MODEL", "gpt-oss:120b")

def call_llm(prompt: str, max_retries: int = 3) -> dict:
    """
    Call the LLM and return a parsed JSON dict.

    Fixes applied:
    - Empty-string guard: LLM returns "" on server overload → explicit retry
    - Markdown fence stripping: model sometimes wraps JSON in ```json ... ```
    - Regex recovery: if JSON is truncated, extract the first complete {} block
    - 502 retry sleep: 5×attempt (5s, 10s, 15s) instead of 2^attempt
      to give the server time to restart
    - No timeout= or max_tokens= in create() — those crash LMStudio backend
    """
    fallback = {
        "decision": "uncertain",
        "confidence": 0.0,
        "reason": "LLM call failed after all retries.",
        "supporting_text": "",
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = _client.chat.completions.create(
                model=MODEL,
                temperature=0.0,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a systematic review screening expert. "
                            "Always respond with valid JSON only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content.strip()

            # Fix 1: empty response guard
            if not raw:
                log.warning("Attempt %d — LLM returned empty response", attempt)
                time.sleep(5 * attempt)
                continue

            # Fix 2: strip markdown fences
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else raw
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            # Fix 3: try direct parse first
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                # Fix 4: regex recovery — extract first complete JSON object
                match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group())
                    except json.JSONDecodeError:
                        pass
                log.warning("Attempt %d — JSON parse failed. Raw: %s", attempt, raw[:100])
                time.sleep(5 * attempt)
                continue

        except Exception as exc:
            log.warning("Attempt %d — LLM error: %s", attempt, exc)
            time.sleep(5 * attempt)

    return fallback
