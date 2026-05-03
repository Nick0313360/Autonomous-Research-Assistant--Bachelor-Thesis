from typing import Tuple, List
from module1.model.SearchQuery import SearchQuery

class PromptBuilder:
    """
    Module 2::Support::PromptBuilder  (NEW — add to class diagram)

    Pure string construction — no IO, no state, no LLM calls.
    Both PrimaryScreener (L2) and UncertaintyHandler (L3) depend on this class.
    Independently testable: unit-test prompt structure without API calls.

    All methods return Tuple[str, str] = (system_prompt, user_prompt).
    """

    def buildPicoText(self, query: SearchQuery) -> str:
        """
        Convert SearchQuery into a single structured PICO criteria string.
        Used by both buildPrimaryPrompt and buildCotPrompt.

        Format:
          Population: {population}
          Intervention: {intervention}
          Comparison: {comparison}   ← omitted if empty
          Outcome: {outcome}
          Research question: {researchQuestion}
        """
        lines = [
            f"Population: {query.population}",
            f"Intervention: {query.intervention}",
        ]
        if query.comparison:
            lines.append(f"Comparison: {query.comparison}")
        lines += [
            f"Outcome: {query.outcome}",
            f"Research question: {query.researchQuestion}",
        ]
        return "\n".join(lines)

    def buildPrimaryPrompt(
        self,
        picoText: str,
        title:    str,
        abstract: str,
    ) -> Tuple[str, str]:
        """
        Build the L2 (PrimaryScreener) prompt pair.

        System prompt instructs the model to:
          - Screen against PICO criteria
          - Respond ONLY with JSON (no markdown, no preamble)
          - Prefer INCLUDE or UNCERTAIN when in doubt (recall-first)

        User prompt structure:
          PICO criteria block
          Title / Abstract block
          JSON schema instruction

        Args:
          picoText: output of buildPicoText()
          title:    paper title
          abstract: paper abstract, caller truncates to 500 chars

        Returns:
          (system, user) strings ready for LLMClient.completeAsync()
        """
        system = (
            "You are a systematic review screener. "
            "Screen the abstract against the PICO criteria. "
            "Respond ONLY with valid JSON — no markdown, no explanation: "
            '{"decision": "INCLUDE"|"EXCLUDE"|"UNCERTAIN", "confidence": 0.0-1.0}. '
            "When in doubt, prefer INCLUDE or UNCERTAIN over EXCLUDE."
        )
        user = (
            f"PICO criteria:\n{picoText}\n\n"
            f"Title: {title}\n"
            f"Abstract: {abstract[:500]}\n\n"
            'Respond ONLY with JSON: {"decision": "INCLUDE"|"EXCLUDE"|"UNCERTAIN", '
            '"confidence": 0.0-1.0}'
        )
        return system, user

    def buildCotPrompt(
        self,
        picoText:  str,
        title:     str,
        abstract:  str,
        examples:  List[dict],
    ) -> Tuple[str, str]:
        """
        Build the L3 (UncertaintyHandler) chain-of-thought prompt pair.

        System prompt instructs the model to:
          - Reason step-by-step through each PICO component
          - Strongly prefer INCLUDE when genuinely uncertain
          - Return structured JSON with step-level reasoning

        User prompt structure:
          Few-shot examples block (from ExampleBuffer, 0–3 examples)
          PICO criteria block
          Paper to evaluate
          JSON schema with step fields

        Args:
          picoText: output of buildPicoText()
          title:    paper title
          abstract: paper abstract, caller truncates to 600 chars
          examples: List[dict] from ExampleBuffer.getSimilar()
                    each dict has keys: title, decision, reasoning

        Returns:
          (system, user) strings ready for LLMClient.completeAsync()
        """
        system = (
            "You are an expert systematic reviewer. "
            "Reason step by step through each PICO component before deciding. "
            "Strongly prefer INCLUDE when uncertain — a false negative is worse "
            "than a false positive at this stage. "
            "Respond ONLY with valid JSON — no markdown, no preamble."
        )

        few_shot_block = ""
        for i, ex in enumerate(examples, start=1):
            few_shot_block += (
                f"\n[Example {i}]\n"
                f"Title: {ex.get('title', '')}\n"
                f"Decision: {ex.get('decision', '')}\n"
                f"Reasoning: {ex.get('reasoning', '')}\n"
            )

        user = (
            f"{few_shot_block}"
            f"\nPICO criteria:\n{picoText}\n\n"
            f"Paper to evaluate:\n"
            f"Title: {title}\n"
            f"Abstract: {abstract[:600]}\n\n"
            "Reason through:\n"
            "1. Does the population match?\n"
            "2. Does the intervention match?\n"
            "3. Is the outcome measurable and relevant?\n"
            "Then decide.\n\n"
            'Respond ONLY with JSON: {'
            '"step1_population": "...", '
            '"step2_intervention": "...", '
            '"step3_outcome": "...", '
            '"decision": "INCLUDE"|"EXCLUDE", '
            '"confidence": 0.0-1.0, '
            '"reasoning": "..."}'
        )
        return system, user

