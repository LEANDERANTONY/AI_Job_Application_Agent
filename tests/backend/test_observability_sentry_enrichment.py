"""M23 — Sentry scope-enrichment helpers.

Analysis (background worker) and artifact export used to reach Sentry as bare,
actor-less 5xx issues — every one looked identical and triage started from
zero. ``set_sentry_user`` / ``set_sentry_tag('pipeline_stage', ...)`` /
``add_sentry_breadcrumb`` / ``set_sentry_context('export', ...)`` add the actor,
the failing stage, and the export descriptor onto the active scope.

The operational contract these tests lock in:
  * enrichment is a clean no-op when Sentry is inactive (the pytest path AND
    prod-without-DSN) — it must not import or call the SDK;
  * when active it forwards to the right SDK call with the right shape;
  * a misbehaving SDK must NEVER raise into the request being decorated.
"""
from __future__ import annotations

import sys

import pytest

from backend import observability


def test_helpers_are_noops_when_sentry_inactive(monkeypatch):
    # Default pytest path: _sentry_active() is False, so nothing is imported or
    # called. The contract is simply "must not raise".
    monkeypatch.setattr(observability, "_sentry_active", lambda: False)
    observability.set_sentry_user("user-1")
    observability.set_sentry_tag("pipeline_stage", "Strategist")
    observability.set_sentry_context("export", {"export_format": "pdf"})
    observability.add_sentry_breadcrumb(category="agent", message="Strategist")


class _FakeSentry:
    """Stand-in for the ``sentry_sdk`` module that records every call."""

    def __init__(self):
        self.user = None
        self.tags: dict = {}
        self.contexts: dict = {}
        self.breadcrumbs: list = []

    def set_user(self, value):
        self.user = value

    def set_tag(self, key, value):
        self.tags[key] = value

    def set_context(self, key, value):
        self.contexts[key] = value

    def add_breadcrumb(self, **kwargs):
        self.breadcrumbs.append(kwargs)


@pytest.fixture
def fake_sentry(monkeypatch):
    """Force enrichment on and swap in a fake SDK via sys.modules.

    ``_sentry_sdk_or_none`` does ``import sentry_sdk``; seeding sys.modules
    makes that import resolve to the fake without a real client.
    """
    fake = _FakeSentry()
    monkeypatch.setattr(observability, "_sentry_active", lambda: True)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    return fake


def test_set_sentry_user_attaches_just_the_id(fake_sentry):
    observability.set_sentry_user("user-42")
    assert fake_sentry.user == {"id": "user-42"}


def test_set_sentry_user_skips_anonymous(fake_sentry):
    observability.set_sentry_user(None)
    observability.set_sentry_user("")
    assert fake_sentry.user is None


def test_set_sentry_tag_and_context_forward(fake_sentry):
    observability.set_sentry_tag("pipeline_stage", "Strategist")
    observability.set_sentry_context("export", {"export_format": "docx"})
    assert fake_sentry.tags["pipeline_stage"] == "Strategist"
    assert fake_sentry.contexts["export"] == {"export_format": "docx"}


def test_add_sentry_breadcrumb_records_category_message_and_data(fake_sentry):
    observability.add_sentry_breadcrumb(
        category="agent", message="Strategist", data={"job_id": "j1"}
    )
    assert len(fake_sentry.breadcrumbs) == 1
    crumb = fake_sentry.breadcrumbs[0]
    assert crumb["category"] == "agent"
    assert crumb["message"] == "Strategist"
    assert crumb["level"] == "info"
    assert crumb["data"] == {"job_id": "j1"}


def test_enrichment_swallows_sdk_errors(monkeypatch):
    """A misbehaving SDK must never break the request being decorated."""

    class _Boom:
        def set_user(self, *a, **k):
            raise RuntimeError("sentry down")

        def set_tag(self, *a, **k):
            raise RuntimeError("sentry down")

        def set_context(self, *a, **k):
            raise RuntimeError("sentry down")

        def add_breadcrumb(self, *a, **k):
            raise RuntimeError("sentry down")

    monkeypatch.setattr(observability, "_sentry_active", lambda: True)
    monkeypatch.setitem(sys.modules, "sentry_sdk", _Boom())
    # None of these may propagate the RuntimeError.
    observability.set_sentry_user("user-1")
    observability.set_sentry_tag("pipeline_stage", "X")
    observability.set_sentry_context("export", {})
    observability.add_sentry_breadcrumb(category="agent", message="X")
