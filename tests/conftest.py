"""Shared pytest fixtures for the backend test suite.

The slowapi limiter persists its bucket state in a module-level
MemoryStorage. When `TestClient` reuses the same simulated client IP
across the whole session, the buckets fill up over time — once the
suite as a whole posts more than `LIMIT_LLM` (30/minute) requests to
`/resume-builder/message`, later tests in that bucket start getting
spurious 429s.

The fix is to clear the storage between every test so each test starts
with a fresh bucket. This is cheap (it's an in-memory dict) and keeps
test ordering insensitivity.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Wipe slowapi's in-memory bucket state before every test.

    autouse=True so individual tests don't have to opt in. The reset
    runs BEFORE the test (not after) — matches the typical
    fresh-process expectation each test has anyway.
    """
    try:
        from backend.rate_limit import limiter
    except Exception:
        # The rate_limit module is optional in some test paths; if it
        # can't import, there's no bucket state to clear.
        yield
        return

    storage = getattr(getattr(limiter, "_limiter", None), "storage", None)
    if storage is not None and hasattr(storage, "reset"):
        storage.reset()
    yield
