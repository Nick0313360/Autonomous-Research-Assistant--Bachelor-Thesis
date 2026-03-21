from typing import List
from pydantic import field_validator, BaseModel
from typing import List, Optional
from datetime import date

class Paper(BaseModel):
        title: str
        abstract: str
        doi: str
        year: int 
        source: str
        pdfLink: Optional[str] = None 
        author: Optional[List[str]] = None

        @field_validator('title', 'abstract', 'doi', 'source')
        def mustNotBeEmpty(cls, v):
            if not v or not v.strip(): 
                raise ValueError("the field can not be empty")
            return v
        
        @field_validator('year')
        def mustBeYear(cls, v): 
            curent_year = date.today().year
            if v <= 0 or v > curent_year:
                raise ValueError(f"The year -> {v} <- is not valid")
            return v

        def toDict(self) -> dict:
            return self.model_dump()
        
