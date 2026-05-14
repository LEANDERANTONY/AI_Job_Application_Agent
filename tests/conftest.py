"""Shared pytest fixtures for the backend test suite.

Two autouse resets keep the suite ordering-insensitive:

  * The slowapi limiter persists its bucket state in a module-level
    MemoryStorage. When `TestClient` reuses the same simulated client
    IP across the whole session, buckets fill up over time and later
    tests get spurious 429s. We clear it between every test.

  * `backend.subscriptions._cached_read` is an lru_cache that lives
    for the whole process. A test that upserts a subscription would
    otherwise leak that cached row into unrelated tests in the same
    pytest run. We clear the cache + in-memory store between every
    test to keep tier resolution starting from a clean slate.
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


@pytest.fixture(autouse=True)
def _reset_subscriptions_cache():
    """Wipe the subscriptions LRU + in-memory store before every test.

    Without this, a test that upserts a subscription row would leak
    that cached entry into unrelated tests in the same pytest run.
    The tier resolver reads through the LRU, so a stale cached row
    silently changes downstream behavior (Free tests suddenly
    resolving as Pro, etc.). Cheap to call -- the cache is tiny.
    """
    try:
        from backend.subscriptions import (
            invalidate_subscription_cache,
            reset_in_memory_backend,
        )
    except Exception:
        # The subscriptions module is optional in some test paths;
        # if it can't import, there's nothing to reset.
        yield
        return

    invalidate_subscription_cache()
    reset_in_memory_backend()
    yield
    invalidate_subscription_cache()
    reset_in_memory_backend()
