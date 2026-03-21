from typing import List, Tuple
from module1.models.Paper import Paper


class DeduplicationService:

    def __init__(self, threshold: float):
        self.__threshold: float = threshold

    def deduplicateByDoi(self, papers: List[Paper]) -> int:
        pass

    def deduplicateByTitle(self, papers: List[Paper]) -> int:
        pass

    def findDuplicates(self, papers: List[Paper]) -> List[Tuple]:
        pass
