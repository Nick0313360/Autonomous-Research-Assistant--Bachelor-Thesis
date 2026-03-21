from typing import List
from datetime import datetime
import uuid
from model.Paper import Paper
from model.SearchQuery import SearchQuery
from model.SearchIteration import SearchIteration
from pydantic import BaseModel, Field, field_validator

class SearchRun(BaseModel):
    runId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    mode: str
    createdAt: datetime = Field(default_factory=datetime.now)
    finalPapers: List[Paper] = Field(default_factory=list)
    totalResults: int = 0
    totalUnique: int = 0
    searchQuery: SearchQuery
    iterations: List[SearchIteration] = Field(default_factory=list)

    @field_validator('mode')
    def mustNotBeEmpty(cls, v):
        if not v or not v.strip():
            raise ValueError(f"mode cannot be empty")
        return v
    
    @field_validator('totalResults', 'totalUnique')
    def mustNotBeLowerZero(cls, v):
        if v < 0:
            raise ValueError(f"{v} cannot be lower than 0")
        return v 
    
    def addIteration(self, iteration: SearchIteration) -> None:
        self.iterations.append(iteration)

    def getLatestPapers(self) -> List[Paper]:
        if not self.iterations:
            return []
        return self.iterations[-1].papers
    
    def computeTotals(self) -> None:
        total_results = 0
        for iteration in self.iterations:
            total_results += iteration.resultCount 
        
        self.totalResults = total_results
        
        self.totalUnique = len(self.finalPapers)