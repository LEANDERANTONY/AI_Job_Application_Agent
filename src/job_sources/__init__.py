"""Provider adapters for backend-owned job search."""

from src.job_sources.demo import DemoJobSourceAdapter
from src.job_sources.greenhouse import GreenhouseJobSourceAdapter
from src.job_sources.lever import LeverJobSourceAdapter

__all__ = [
    "DemoJobSourceAdapter",
    "GreenhouseJobSourceAdapter",
    "LeverJobSourceAdapter",
]
