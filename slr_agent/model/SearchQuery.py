from typing import List, Optional, Tuple
from pydantic import field_validator, BaseModel

class SearchQuery(BaseModel):
    researchQuestion: str 
    researchQuestion: str 
    population : str
    intervention: str 
    comparison: Optional[str] = None
    outcome: str 
    domainKeywords: List[str]
    year_range: Optional[Tuple[int, int]] = None
    maxPapersPerDb: int 

    @field_validator('researchQuestion', 'intervention', 'population', 'outcome', 'maxPapersPerDb')    
    def mustNotEmpty(cls, v):
        if not v or not v.strip():
            return ValueError(f"{v} Is empty field")
        return v
    
    @field_validator('maxPapersPerDb')
    def mustNotBeLowerThanZero(cls, v):
        if v < 0:
            return ValueError(f"{v} can not be lower than 0")
        return v         

    def toDict(self) -> dict:
        return self.model_dump()
    
    def validate(self) -> bool:
        if self.year_range:
            start, end = self.year_range
            if start > end:
                return False
        
        if self.comparison and self.comparison == self.intervention:
            return False
        
        return True

    def buildQueryString(self) -> str:
        parts = []

        fields = ['population', 'intervention', 'outcome']
        if self.comparison:
            fields.append(self.comparison)
        
        for field_name in fields:
            field_value = getattr(self, field_name)
            if field_value:
                synonims = [term.strip() for term in field_value.split(',') if term.strip()]

                if len(synonims) == 1:
                    parts.append(synonims[0])
                elif len(synonims) > 1:
                    or_parts = ' OR '.join(synonims)
                    parts.append(f'({or_parts})')

            if not parts:
                print("⚠️ WARNING: No valid PICO fields found to build query string")
                return ''
            
            return ' AND '.join(parts)