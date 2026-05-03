from typing import List
from module1.model.Paper import Paper
from module1.model.SearchRun import SearchRun
from module1.model.SearchQuery import SearchQuery
from module1.connector.BaseConnector import BaseConnector
from module1.services.LLMRefinerService import LLMRefinerService
from module1.services.DeduplicationService import DeduplicationService


class SearchService:
    def __init__(self, connectors: List[BaseConnector], deduplicator: DeduplicationService, refiner: LLMRefinerService):
        self.__connectors: List[BaseConnector] = connectors
        self.__deduplicator: DeduplicationService = deduplicator
        self.__refiner: LLMRefinerService = refiner

    def runSearch(self, searchQuery: SearchQuery, mode: str) -> SearchRun:
        pass

    def __runBasic(self, searchQuery: SearchQuery) -> SearchRun:
        pass

    def __runIterative(self, searchQuery: SearchQuery) -> SearchRun:
        pass

    def __executeQuery(self, queryStr: str) -> List[Paper]:
        pass

    def __mergeResults(self, results: List[List[Paper]]) -> List[Paper]:
        pass
