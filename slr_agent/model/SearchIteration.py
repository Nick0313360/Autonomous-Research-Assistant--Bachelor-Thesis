from typing import List, Optional
from Paper import Paper
from RefinementResult import RefinementResult
from pydantic import BaseModel, field_validator


class SearchIteration(BaseModel):
    iterationNumber: int
    queryString: str 
    newTerms: List[str] = []
    papers: List[Paper] = []
    resultCount: int = 0
    refinementResult: Optional[RefinementResult] = None

    @field_validator('iterationNumber', 'queryString')
    def mustNotBeEmplty(cls, v):
        if not v or not v.strip():
            return ValueError(f"{v} can not be empty")
        return v
    
    def toDict(self) -> dict:
        return self.model_dump()
    
    def summary(self) -> str:
        return f"iteration{self.iterationNumber} - {self.resultCount} papers - {len(self.newTerms)} new terms added"
