from pydantic import field_validator, BaseModel

class TermDecision(BaseModel):
    term: str
    accepted: bool
    reason: str

    @field_validator('term', 'reason')
    def mustNotBeEmpty(cls, v):
        if not v or not v.strip():
                raise ValueError(f"fielf can not be empty {v}")
        return v
    
    def toDict(self) -> dict: 
        return self.model_dump()
        


        