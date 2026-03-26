from typing import List, Optional
from model.Paper import Paper
from model.RefinementResult import RefinementResult
from pydantic import BaseModel, field_validator


class SearchIteration(BaseModel):
    iterationNumber: int
    queryString: str 
    newTerms: List[str] = []
    papers: List[Paper] = []
    resultCount: int = 0
    refinementResult: Optional[RefinementResult] = None

    @field_validator('queryString')
    def mustNotBeEmpty(cls, v):
        if not v or not v.strip():
            raise ValueError(f"{v} cannot be empty")
        return v
    
    @field_validator('iterationNumber')
    def mustBePositive(cls, v):
        if v <= 0:
            raise ValueError(f"{v} must be positive")
        return v
    
    @field_validator('resultCount')
    def mustNotBeNegative(cls, v):
        if v < 0:
            raise ValueError(f"{v} cannot be negative")
        return v
    
    def toDict(self) -> dict:
        return self.model_dump()
    
    def summary(self) -> str:
        return f"iteration {self.iterationNumber} - {self.resultCount} papers - {len(self.newTerms)} new terms added"