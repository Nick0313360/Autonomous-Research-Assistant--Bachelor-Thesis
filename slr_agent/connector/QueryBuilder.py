from typing import List
from model.SearchQuery import SearchQuery

class QueryBuilder:
    def __init__(self):
        pass
    
    def buildPubmed(self, searchQuery: SearchQuery) -> str:
        slots = self.__collectSlots(searchQuery)
        if not slots:
            return searchQuery.researchQuestion
        
        clauses = []
        for slot in slots: 
            synonyms = [s.strip() for s in slot.split(',') if s.strip()]
            if not synonyms:
                continue
            tagged = [f'"{s}"[TIAB]' for s in synonyms]
            clauses.append(f"({' OR '.join(tagged)})")

        return " AND ".join(clauses)

    def buildSemantic(self, searchQuery: SearchQuery) -> str:
        slots = self.__collectSlots(searchQuery)
        if not slots:
            return searchQuery.researchQuestion

        keywords = []
        for slot in slots:
            terms = [s.strip() for s in slot.split(",") if s.strip()]
            keywords.extend(terms)

        query = " ".join(keywords)
        if len(query) > 200:
            query = query[:200].rsplit(" ", 1)[0]
        return query

    def __collectSlots(self, searchQuery: SearchQuery) -> List[str]:
        slots = []
        if searchQuery.population:
            slots.append(searchQuery.population)
        if searchQuery.intervention:
            slots.append(searchQuery.intervention)
        if searchQuery.outcome:
            slots.append(searchQuery.outcome)
        if searchQuery.comparison:
            slots.append(searchQuery.comparison)
        return slots

