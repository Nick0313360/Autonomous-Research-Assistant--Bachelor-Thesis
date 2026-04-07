from abc import ABC
from typing import List
from module1.model.Paper import Paper

class BaseConnector(ABC):
    def __init__(self, apiKey: str, baseUrl: str):
        if not apiKey or not apiKey.strip():
            raise ValueError("No api key is provided")
        if not baseUrl or not baseUrl.strip():
            raise ValueError("No base URL is provided")
        
        self.__apiKey: str = apiKey
        self.__baseUrl: str = baseUrl

    @property
    def apiKey(self) -> str:
        return self.__apiKey

    @property
    def baseUrl(self) -> str:
        return self.__baseUrl

    def fetchPapers(self, query: str, maxResults: int) -> List[Paper]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support fetchPapers"
        )