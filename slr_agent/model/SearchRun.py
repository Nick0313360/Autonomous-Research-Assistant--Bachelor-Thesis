from typing import List
from datetime import datetime
import uuid
from Paper import Paper
from SearchQuery import SearchQuery
from SearchIteration import SearchIteration
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
        
        if self.searchQuery.year_range:
            target_year = self.searchQuery.year_range[1]
        else:
            target_year = 0
            for iteration in self.iterations:
                for paper in iteration.papers:
                    if paper.year > target_year:
                        target_year = paper.year
        
        latest_papers = []
        for iteration in self.iterations:
            for paper in iteration.papers:
                if paper.year == target_year:
                    latest_papers.append(paper)
        
        return latest_papers
    
    def computeTotals(self) -> None:
        total_results = 0
        for iteration in self.iterations:
            total_results += iteration.resultCount 
        
        self.totalResults = total_results
        
        self.totalUnique = len(self.finalPapers)