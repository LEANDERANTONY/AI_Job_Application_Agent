"""Read-only /workspace/quota snapshot endpoint (Step 7b).

These tests pin the contract the frontend reads from
GET /workspace/quota. The endpoint drives:

  * The Premium toggle's enabled / disabled state via
    `premium_available`.
  * Per-counter "remaining N of M" indicators rendered next to the
    toggle and (eventually) inline on each workspace step.
  * The upgrade CTA target URL, env-configurable via
    AIJOBAGENT_UPGRADE_URL.

Hard rules pinned below:

  * Read-only — calling /workspace/quota MUST NOT increment any
    counter or burn quota credit. We assert this by inspecting the
    in-memory backend state before/after the call.
  * Every counter in TIER_CAPS appears in the response, with
    {current, limit, remaining, reset_period} for each. Missing
    a counter is a UI regression.
  * Anonymous calls get a 401, not a synthetic free snapshot —
    leaking cap numbers on an unauthed probe would invite scraping.
  * Premium-availability gate: Free tier returns
    `premium_available=False` (cap=0), Pro/Business return True.
    The shim resolves everyone to Free today, so the test covers
    the Free path; the Pro/Business path is exercised by patching
    `resolve_user_tier` directly.
"""
from __future__ import annotations

import pytest

from backend import quota
from backend.services import workspace_quota_service
from backend.tiers import TIER_CAPS


@pytest.fixture(autouse=True)
def _fresh_quota_store(monkeypatch):
    """Reset the in-memory quota store between tests so an earlier
    test's increment doesn't leak into this one's snapshot."""

    class _NeverConfigured:
        def is_configured(self):
            return False

    monkeypatch.setattr(quota, "_SUPABASE_BACKEND", _NeverConfigured())
    # T4 of the token-meter migration loosened tailored_applications to
    # UNLIMITED. The snapshot tests below use it as the example
    # incremented counter to verify the read-only snapshot reflects
    # check_and_increment writes; pin its pre-migration finite cap so
    # the increment actually writes a countable row.
    for _tier, _cap in (("free", 3), ("pro", 20), ("business", 80)):
        monkeypatch.setitem(quota.TIER_CAPS[_tier], "tailored_applications", _cap)
    quota.reset_in_memory_backend()
    yield
    quota.reset_in_memory_backend()


# ─── helpers ──────────────────────────────────────────────────────────


class _FakeAuthService:
    """Minimal AuthService stand-in. The Saved* stores' is_configured()
    checks talk to this; returning False is enough to keep the
    snapshot off the Supabase round-trip path for persistent
    counters."""

    @staticmethod
    def is_configured():
        return False


class _FakeAppUser:
    def __init__(self, user_id: str = "user-123"):
        self.id = user_id


class _FakeAuthContext:
    def __init__(self, user_id: str = "user-123"):
        self.auth_service = _FakeAuthService()
        self.app_user = _FakeAppUser(user_id)


@pytest.fixture
def fake_auth(monkeypatch):
    """Patch `resolve_authenticated_context` so the snapshot doesn't
    need a real Supabase round-trip. Returns the fake context so
    individual tests can read `app_user.id` if needed."""
    context = _FakeAuthContext()

    def _resolve(*, access_token, refresh_token):
        if not (access_token and refresh_token):
            raise RuntimeError("test stub: tokens missing")
        return context

    monkeypatch.setattr(
        workspace_quota_service,
        "resolve_authenticated_context",
        _resolve,
    )
    return context


# ─── tests ────────────────────────────────────────────────────────────


def test_snapshot_shape_contains_every_tier_cap_counter(fake_auth):
    """The response's `counters` dict must cover every counter in
    TIER_CAPS — a missing key would silently break the UI's per-
    counter indicator."""
    snapshot = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    assert set(snapshot["counters"].keys()) == set(TIER_CAPS["free"].keys())


def test_snapshot_free_tier_has_premium_disabled(fake_auth):
    """Free tier resolves premium_available=False because the
    premium_applications cap is 0 — the toggle renders disabled with
    an 'Upgrade to Pro' tooltip."""
    snapshot = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    assert snapshot["tier"] == "free"
    assert snapshot["premium_available"] is False


def test_snapshot_pro_tier_has_premium_enabled(fake_auth, monkeypatch):
    """Pro tier resolves premium_available=True because the
    premium_applications cap is > 0. We patch resolve_user_tier
    because the shim returns 'free' for everyone today; this test
    covers the Pro/Business path the UI will exercise once Stripe
    lands."""
    monkeypatch.setattr(
        workspace_quota_service,
        "resolve_user_tier",
        lambda _user: "pro",
    )
    snapshot = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    assert snapshot["tier"] == "pro"
    assert snapshot["premium_available"] is True
    # The premium counter on Pro is 5 with 0 used at snapshot time.
    assert snapshot["counters"]["premium_applications"]["limit"] == 5
    assert snapshot["counters"]["premium_applications"]["current"] == 0
    assert snapshot["counters"]["premium_applications"]["remaining"] == 5


def test_snapshot_reflects_existing_counter_usage(fake_auth):
    """An earlier `check_and_increment` must be visible to a later
    snapshot read. This is the contract that makes the Premium-toggle
    indicator 'live' — after the workflow consumes a credit, the
    next /workspace/quota call shows the decrement."""
    # Burn one tailored_applications credit for the fake user.
    quota.check_and_increment(
        "tailored_applications",
        fake_auth.app_user.id,
        "free",
    )
    snapshot = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    tailored = snapshot["counters"]["tailored_applications"]
    assert tailored["current"] == 1
    assert tailored["limit"] == 3
    assert tailored["remaining"] == 2


def test_snapshot_does_not_increment_any_counter(fake_auth):
    """Read-only invariant: calling /workspace/quota MUST NOT bump
    any counter. We compare a snapshot taken before and after a
    handful of repeat calls — the values stay constant."""
    # Seed an existing increment so we have a non-zero counter to
    # compare against (zero-vs-zero would pass trivially).
    quota.check_and_increment(
        "tailored_applications",
        fake_auth.app_user.id,
        "free",
    )

    before = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    # Call it a few more times — the snapshot read must not increment
    # any counter even after repeated invocations.
    for _ in range(3):
        workspace_quota_service.get_workspace_quota_snapshot(
            access_token="access",
            refresh_token="refresh",
        )
    after = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    assert before["counters"] == after["counters"]
    # Defensive: assert the specific counter we incremented is still
    # at the same value the gate set it to.
    assert after["counters"]["tailored_applications"]["current"] == 1


def test_snapshot_anonymous_caller_raises_auth_required():
    """Anonymous callers (no tokens) must NOT receive a synthetic
    free snapshot — that would leak per-tier cap numbers on an
    unauthed probe. The route translates this to 401."""
    with pytest.raises(workspace_quota_service.WorkspaceQuotaAuthRequired):
        workspace_quota_service.get_workspace_quota_snapshot(
            access_token="",
            refresh_token="",
        )


def test_snapshot_carries_upgrade_url(fake_auth, monkeypatch):
    """The /workspace/quota response surfaces an upgrade_url so the
    frontend's CTA can deep-link to the pricing page. The URL is
    env-configurable via AIJOBAGENT_UPGRADE_URL."""
    # Cover the env-driven default first.
    snapshot = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    assert snapshot["upgrade_url"].startswith("https://")

    # Now patch the constant to verify the field is wired to it.
    monkeypatch.setattr(quota, "UPGRADE_URL", "https://example.test/upgrade")
    snapshot_after = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    assert snapshot_after["upgrade_url"] == "https://example.test/upgrade"


def test_snapshot_persistent_counters_have_persistent_reset_period(fake_auth):
    """saved_jobs and saved_workspaces are persistent — they don't
    reset on a calendar boundary. The reset_period label drives the
    UI's per-counter copy ('resets monthly' vs 'persistent storage'),
    so it has to be correct."""
    snapshot = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    assert snapshot["counters"]["saved_jobs"]["reset_period"] == "persistent"
    assert (
        snapshot["counters"]["saved_workspaces"]["reset_period"] == "persistent"
    )


def test_snapshot_resume_builder_session_reset_period_for_free_is_lifetime(
    fake_auth,
):
    """The resume_builder_sessions gate writes to a "lifetime"
    period_key for Free tier (so a Free user's single onboarding
    isn't refreshed by a new month). The snapshot's reset_period
    must mirror that so the UI doesn't promise a non-existent monthly
    reset."""
    snapshot = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    assert (
        snapshot["counters"]["resume_builder_sessions"]["reset_period"]
        == "lifetime"
    )


def test_snapshot_reflects_weekly_llm_token_usage(fake_auth):
    """The unified token meter (`llm_tokens`) lives under an ISO-week
    period key — `read_counter` would read the monthly partition and
    report 0. The snapshot must use the weekly reader so the UI usage
    bar shows the real spend, with reset_period 'weekly'."""
    quota.record_llm_token_usage(fake_auth.app_user.id, 24_000)

    snapshot = workspace_quota_service.get_workspace_quota_snapshot(
        access_token="access",
        refresh_token="refresh",
    )
    llm = snapshot["counters"]["llm_tokens"]
    assert llm["current"] == 24_000
    assert llm["limit"] == TIER_CAPS["free"]["llm_tokens"] == 90_000
    assert llm["remaining"] == 66_000
    assert llm["reset_period"] == "weekly"
    # Top-level reset date drives the usage bar's "resets X" copy.
    reset_at = snapshot["llm_tokens_reset_at"]
    assert isinstance(reset_at, str) and reset_at.count("-") == 2
