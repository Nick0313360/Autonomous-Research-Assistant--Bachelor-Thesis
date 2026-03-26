from typing import List
from model.Paper import Paper
from model.SearchQuery import SearchQuery
from model.SearchRun import SearchRun
from connector.BaseConnector import BaseConnector
from services.DeduplicationService import DeduplicationService
from services.LLMRefinerService import LLMRefinerService


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
