from src.job_sources.base import JobSourceAdapter
from src.job_sources.demo import DemoJobSourceAdapter
from src.job_sources.greenhouse import GreenhouseJobSourceAdapter
from src.job_sources.lever import LeverJobSourceAdapter


def build_default_job_sources() -> list[JobSourceAdapter]:
    return [
        GreenhouseJobSourceAdapter(),
        LeverJobSourceAdapter(),
        DemoJobSourceAdapter(),
    ]
