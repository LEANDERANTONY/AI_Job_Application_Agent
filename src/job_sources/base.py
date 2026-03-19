from abc import ABC, abstractmethod

from src.schemas import JobResolutionResult, JobSearchQuery, JobSourceSearchResponse


class JobSourceAdapter(ABC):
    source_name = "unknown"

    @abstractmethod
    def can_resolve_url(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def search(self, query: JobSearchQuery) -> JobSourceSearchResponse:
        raise NotImplementedError

    @abstractmethod
    def resolve_url(self, url: str) -> JobResolutionResult:
        raise NotImplementedError
