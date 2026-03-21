from typing import List
from TermDecision import TermDecision
from pydantic import BaseModel

class RefinementResult(BaseModel):
    acceptedTerms: List[str] = []
    rejectedTerms: List[TermDecision] = []
    expandedQuery: str = ""
    llmRawOutput: str = ""
    error: str = ""

    def acceptanceRate(self) -> float:
        total = len(self.acceptedTerms) + len(self.rejectedTerms)
        if total == 0:
            return 0.0
        return len(self.acceptedTerms) / total

    def toDict(self) -> dict:
        return self.model_dump()
