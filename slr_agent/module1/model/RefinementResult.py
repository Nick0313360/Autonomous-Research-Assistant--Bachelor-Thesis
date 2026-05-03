from typing import List
from pydantic import BaseModel
from module1.model.TermDecision import TermDecision

class RefinementResult(BaseModel):
    iteration: int = 0
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
