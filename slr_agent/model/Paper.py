from typing import List, Optional
from datetime import date
from pydantic import BaseModel, field_validator


class Paper(BaseModel):
    title: str
    abstract: Optional[str] = None
    doi: Optional[str] = None
    year: int
    source: str
    pdfLink: Optional[str] = None
    author: Optional[List[str]] = None

    @field_validator('title', 'source')
    def mustNotBeEmpty(cls, v):
        if not v or not v.strip():
            raise ValueError("the field can not be empty")
        return v

    @field_validator('year')
    def mustBeYear(cls, v):
        currentYear = date.today().year
        if v <= 0 or v > currentYear:
            raise ValueError(f"the year {v} is not valid")
        return v

    def toDict(self) -> dict:
        return self.model_dump()