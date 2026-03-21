import logging
from typing import List, Set, Optional

from connector.GptConnector import GptConnector
from model.Paper import Paper
from model.SearchQuery import SearchQuery
from model.RefinementResult import RefinementResult
from model.TermDecision import TermDecision
from services.DomainValidator import DomainValidator
from services.PaperSampler import PaperSampler

logger = logging.getLogger(__name__)


class LLMRefinerService:
    """
    Smart query refinement service.
    Knows WHAT to do with the LLM — all decision logic lives here.
    Domain-agnostic: works for medicine, law, IT, biology, or any field.
    The SearchQuery object carries the domain context — this service
    reads it and adapts the prompt dynamically.
    """

    __MIN_PAPERS_WITH_ABSTRACT: int = 5
    __MAX_NEW_TERMS: int = 5

    def __init__(
        self,
        llm: GptConnector,
        validator: DomainValidator,
        sampler: PaperSampler,
    ):
        self.__llm: GptConnector = llm
        self.__validator: DomainValidator = validator
        self.__sampler: PaperSampler = sampler

    def refineQuery(
        self,
        papers: List[Paper],
        currentQuery: str,
        searchQuery: SearchQuery,
        usedTerms: Set[str],
        iteration: int,
    ) -> RefinementResult:
        """
        Full refinement pipeline for one iteration:
          1. Check we have enough context
          2. Sample papers and build context block
          3. Build a domain-aware prompt from SearchQuery fields
          4. Call LLM
          5. Validate each suggested term
          6. Return typed RefinementResult

        usedTerms is mutated in place — terms accepted this iteration
        are added so the next iteration does not suggest them again.
        """
        result = RefinementResult()
        result.iteration = iteration

        # guard — need enough abstracts to give LLM useful context
        papersWithAbstract = [p for p in papers if p.abstract]
        if len(papersWithAbstract) < self.__MIN_PAPERS_WITH_ABSTRACT:
            logger.warning(
                "LLMRefinerService: only %d papers have abstracts, minimum is %d. Skipping.",
                len(papersWithAbstract), self.__MIN_PAPERS_WITH_ABSTRACT
            )
            result.error = f"insufficient_context: {len(papersWithAbstract)} papers with abstracts"
            result.expandedQuery = currentQuery
            return result

        # build context from sampled papers
        sample = self.__sampler.sample(papersWithAbstract, n=20)
        contextBlock = self.__sampler.buildContext(sample)

        # build prompt — fully dynamic from SearchQuery, no hardcoded domain
        prompt = self.__buildPrompt(
            currentQuery=currentQuery,
            searchQuery=searchQuery,
            contextBlock=contextBlock,
            usedTerms=usedTerms,
        )

        systemMessage = (
            "You are an expert academic search strategist. "
            "Your job is to suggest missing search terms for a systematic literature review. "
            "Reply ONLY with a comma-separated list of terms. No explanations. No numbering."
        )

        # call LLM
        rawOutput = self.__llm.callLlm(prompt=prompt, systemMessage=systemMessage)
        result.llmRawOutput = rawOutput

        if not rawOutput.strip():
            logger.info("LLMRefinerService: LLM returned empty response — no suggestions this iteration")
            result.expandedQuery = currentQuery
            return result

        # validate each suggested term
        candidateTerms = [t.strip().lower() for t in rawOutput.split(",") if t.strip()]

        for term in candidateTerms:
            decision = self.__validateTerm(
                term=term,
                currentQuery=currentQuery,
                searchQuery=searchQuery,
                usedTerms=usedTerms,
            )
            if decision.accepted:
                result.acceptedTerms.append(term)
                usedTerms.add(term)
                if len(result.acceptedTerms) >= self.__MAX_NEW_TERMS:
                    break
            else:
                result.rejectedTerms.append(decision)

        result.expandedQuery = self.expandQuery(currentQuery, result.acceptedTerms)
        return result

    def expandQuery(self, query: str, terms: List[str]) -> str:
        """
        Appends accepted terms to the current query with OR.
        Multi-word terms get quoted to preserve phrase semantics.
        Pure function — no side effects.
        """
        if not terms:
            return query

        formatted = []
        for term in terms:
            formatted.append(f'"{term}"' if " " in term else term)

        return query + " OR " + " OR ".join(formatted)

    # ──────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────

    def __buildPrompt(
        self,
        currentQuery: str,
        searchQuery: SearchQuery,
        contextBlock: str,
        usedTerms: Set[str],
    ) -> str:
        """
        Builds the full LLM prompt dynamically from SearchQuery fields.
        Domain agnostic — the research question and PICO fields define the domain,
        not any hardcoded vocabulary list.
        """
        # domain context block — built from whatever the SearchQuery contains
        domainLines = [f"Research question: {searchQuery.researchQuestion}"]

        if searchQuery.population:
            domainLines.append(f"Population / domain: {searchQuery.population}")
        if searchQuery.intervention:
            domainLines.append(f"Intervention / focus: {searchQuery.intervention}")
        if searchQuery.outcome:
            domainLines.append(f"Outcome of interest: {searchQuery.outcome}")
        if searchQuery.comparison:
            domainLines.append(f"Comparison: {searchQuery.comparison}")
        if searchQuery.domainKeywords:
            domainLines.append(f"Domain anchors: {', '.join(searchQuery.domainKeywords)}")

        domainBlock = "\n".join(domainLines)

        usedBlock = ""
        if usedTerms:
            usedBlock = f"\nAlready used terms — do NOT suggest these: {', '.join(list(usedTerms)[:20])}"

        return f"""You are an expert systematic review search strategist.

{domainBlock}

Current query:
{currentQuery}
{usedBlock}

Papers retrieved so far (sample of titles and abstracts):
{contextBlock}

Task:
Suggest up to {self.__MAX_NEW_TERMS} NEW search terms or short phrases that:
  1. Appear in the papers above or are closely related to them
  2. Are MISSING from the current query
  3. Are STRICTLY within the domain and topic defined above
  4. Would retrieve MORE relevant papers if added

Do NOT suggest:
  - Generic terms like "research", "study", "analysis", "review"
  - Terms from unrelated fields
  - Terms already listed as already used
  - Statistical metrics like "precision", "recall", "accuracy" unless they are core to the domain

Return ONLY a comma-separated list of terms. Nothing else.
"""

    def __validateTerm(
        self,
        term: str,
        currentQuery: str,
        searchQuery: SearchQuery,
        usedTerms: Set[str],
    ) -> TermDecision:
        """
        Runs all validation guards on one candidate term.
        Returns a TermDecision with accepted=True only if all guards pass.
        """
        if not term or len(term) < 3:
            return TermDecision(term=term, accepted=False, reason="too_short")

        if term in currentQuery.lower():
            return TermDecision(term=term, accepted=False, reason="already_in_query")

        if term in usedTerms:
            return TermDecision(term=term, accepted=False, reason="already_used")

        relevant, reason = self.__validator.isRelevant(
            term=term,
            domainKeywords=searchQuery.domainKeywords,
            researchQuestion=searchQuery.researchQuestion,
        )

        if not relevant:
            logger.info("LLMRefinerService: term rejected (%s): '%s'", reason, term)
            return TermDecision(term=term, accepted=False, reason=reason)

        return TermDecision(term=term, accepted=True, reason=reason)


# DELETE BEFORE PRODUCTION — smoke test
# run: python -m module1.services.LLMRefinerService
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO)

    from module1.services.DomainValidator import DomainValidator
    from module1.services.PaperSampler import PaperSampler

    llm = GptConnector(
        baseUrl=os.getenv("OPENAI_BASE_URL", "https://inference.mlmp.ti.bfh.ch/api/v1"),
        apiKey=os.getenv("OPENAI_API_KEY", ""),
        modelName=os.getenv("OPENAI_MODEL", "gpt-oss:120b"),
    )

    validator = DomainValidator(vocabulary=frozenset())
    sampler = PaperSampler()
    refiner = LLMRefinerService(llm=llm, validator=validator, sampler=sampler)

    # mock SearchQuery for testing — change fields to test different domains
    class MockSearchQuery:
        researchQuestion = "How do LLMs automate systematic review screening?"
        population = "systematic reviews, literature reviews"
        intervention = "LLM, GPT, large language model, AI agent"
        outcome = "screening accuracy, automation"
        comparison = None
        domainKeywords = ["systematic review", "LLM", "screening", "PRISMA"]

    # mock papers
    mockPapers = [
        Paper(title="GPT-4 for title screening in SLR", abstract="We evaluate GPT-4 on abstract screening tasks achieving 91% recall.", doi=None, year=2024, source="test", pdfLink=None, author=[]),
        Paper(title="Automated citation screening using BERT", abstract="BERT fine-tuned on inclusion criteria outperforms traditional methods.", doi=None, year=2023, source="test", pdfLink=None, author=[]),
        Paper(title="LLM agents for evidence synthesis", abstract="We propose an agent-based pipeline for PRISMA-compliant evidence synthesis.", doi=None, year=2024, source="test", pdfLink=None, author=[]),
        Paper(title="Active learning for systematic review automation", abstract="Active learning reduces human screening effort by 60% while maintaining recall.", doi=None, year=2022, source="test", pdfLink=None, author=[]),
        Paper(title="RAG-based data extraction from clinical trials", abstract="Retrieval augmented generation extracts structured data from full-text PDFs.", doi=None, year=2024, source="test", pdfLink=None, author=[]),
    ]

    usedTerms = set()
    currentQuery = '("systematic review"[TIAB]) AND ("LLM"[TIAB] OR "GPT"[TIAB])'

    print("Running LLMRefinerService smoke test...")
    print(f"Current query: {currentQuery}")
    print("-" * 50)

    result = refiner.refineQuery(
        papers=mockPapers,
        currentQuery=currentQuery,
        searchQuery=MockSearchQuery(),
        usedTerms=usedTerms,
        iteration=1,
    )

    print(f"LLM raw output  : {result.llmRawOutput}")
    print(f"Accepted terms  : {result.acceptedTerms}")
    print(f"Rejected terms  : {[(d.term, d.reason) for d in result.rejectedTerms]}")
    print(f"Acceptance rate : {result.acceptanceRate():.0%}")
    print(f"Expanded query  : {result.expandedQuery}")
    print(f"Error           : {result.error or 'none'}")
    print("\nSmoke test complete.")