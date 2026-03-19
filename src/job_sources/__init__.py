"""Provider adapters for backend-owned job search."""

from src.job_sources.demo import DemoJobSourceAdapter
from src.job_sources.greenhouse import GreenhouseJobSourceAdapter

__all__ = [
    "DemoJobSourceAdapter",
    "GreenhouseJobSourceAdapter",
]
