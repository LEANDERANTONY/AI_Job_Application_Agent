"""Quota enforcement for resume parse + resume-builder session creation.

Step 5 of the tier-enforcement series. Two counters, two endpoints:

  * `resume_parses` is monthly:
        Free 3 / Pro 25 / Business 100.
    The gate runs inside ``parse_resume_upload`` BEFORE the actual
    document parse so we don't burn the parse if we'd just reject.

  * `resume_builder_sessions` is the special case:
        Free uses a LIFETIME counter (cap 1, one onboarding ever).
        Pro / Business use MONTHLY counters (cap 3 / 15).
    The gate runs inside ``start_resume_builder_session`` -- the
    credit is consumed on session creation, not per intake turn.

What we verify:

  Resume parse
    * 4th parse on Free  -> 429 (cap=3)
    * 26th parse on Pro  -> 429 (cap=25)
    * Parser exception   -> counter refunded
    * Anonymous upload   -> skip gate

  Resume builder session
    * 2nd session on Free      -> 429 (cap=1, lifetime)
    * 4th session on Pro       -> 429 (cap=3, monthly)
    * Free uses "lifetime" period_key, Pro uses YYYY-MM -- verified
      by burning Free's lifetime cap, then forcing the tier to Pro
      with a fresh monthly partition still available
    * Session-creation failure -> counter refunded
    * Anonymous start          -> skip gate
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend import quota
from backend.quota import (
    LIFETIME_PERIOD_KEY,
    current_period_key,
    reset_in_memory_backend,
)
from backend.services import resume_builder_service, workspace_service
from backend.services.auth_session_service import AuthenticatedContext
from backend.tiers import TIER_CAPS
from src.auth_service import AuthSession, AuthUser
from src.errors import QuotaExceededError
from src.schemas import AppUserRecord


# ─── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_quota_backend(monkeypatch):
    """Force the in-memory quota backend with empty state. Mirrors the
    pattern in test_workspace_quota_enforcement / test_assistant_quota_enforcement."""

    class _NeverConfigured:
        def is_configured(self) -> bool:
            return False

    monkeypatch.setattr(quota, "_SUPABASE_BACKEND", _NeverConfigured())
    # T4 of the token-meter migration loosened resume_parses and
    # resume_builder_sessions to UNLIMITED in the production TIER_CAPS.
    # The gate CODE in parse_resume_upload / start_resume_builder_session
    # is still present and revertable ("not a hard swap"), so this file
    # pins the pre-migration finite caps to verify that gate machinery
    # still fires ("Nth call -> 429"). This mirrors the autouse cap-
    # pinning in test_workspace_quota_enforcement (tailored_applications)
    # and test_assistant_quota_enforcement (assistant_turns). The
    # production cap POLICY (UNLIMITED) is asserted in test_tiers.py; the
    # LIVE LLM gate for these routes is the unified llm_tokens meter.
    for _tier, _cap in (("free", 3), ("pro", 25), ("business", 100)):
        monkeypatch.setitem(quota.TIER_CAPS[_tier], "resume_parses", _cap)
    for _tier, _cap in (("free", 1), ("pro", 3), ("business", 15)):
        monkeypatch.setitem(quota.TIER_CAPS[_tier], "resume_builder_sessions", _cap)
    reset_in_memory_backend()
    yield
    reset_in_memory_backend()


@pytest.fixture(autouse=True)
def _fresh_builder_sessions():
    """Resume builder uses a module-level dict for in-memory sessions.
    Clear it between tests so a leaked session can't influence
    downstream cases."""
    resume_builder_service._SESSIONS.clear()
    yield
    resume_builder_service._SESSIONS.clear()


def _build_auth_context(*, user_id: str = "user-test", email: str = "u@example.com"):
    auth_session = AuthSession(
        access_token="access",
        refresh_token="refresh",
        user=AuthUser(user_id=user_id, email=email),
    )
    app_user = AppUserRecord(id=user_id, email=email)
    return AuthenticatedContext(
        auth_service=None,  # type: ignore[arg-type] - unused
        auth_session=auth_session,
        app_user=app_user,
        daily_quota=None,
    )


@pytest.fixture
def stub_resume_parser(monkeypatch):
    """Replace the parse + profile-build steps so a quota test never
    has to construct a real PDF / DOCX corpus. We still exercise the
    `_decode_base64_content` call so payload validation is real."""
    from src.schemas import CandidateProfile, ResumeDocument

    resume_document = ResumeDocument(
        text="resume body",
        filetype="TXT",
        source="workspace:test.txt",
    )
    profile = CandidateProfile(
        full_name="Test",
        source="test",
        resume_text="resume body",
    )

    monkeypatch.setattr(
        workspace_service,
        "parse_resume_document",
        lambda _fh, source=None: resume_document,
    )
    monkeypatch.setattr(
        workspace_service,
        "build_candidate_profile_from_resume_auto",
        lambda _doc, **_kwargs: profile,
    )


def _b64_payload() -> str:
    import base64

    return base64.b64encode(b"resume body").decode("ascii")


def _parse(*, auth_context=None):
    """Drive parse_resume_upload directly with the supplied auth context."""

    def _resolver(*, access_token=None, refresh_token=None):
        return auth_context

    with patch.object(
        workspace_service,
        "resolve_authenticated_context",
        _resolver,
    ):
        return workspace_service.parse_resume_upload(
            filename="resume.txt",
            mime_type="text/plain",
            content_base64=_b64_payload(),
            access_token="access" if auth_context else "",
            refresh_token="refresh" if auth_context else "",
        )


def _start_builder(*, auth_context=None):
    """Drive start_resume_builder_session directly."""

    def _resolver(*, access_token=None, refresh_token=None):
        return auth_context

    with patch.object(
        resume_builder_service,
        "resolve_authenticated_context",
        _resolver,
    ):
        return resume_builder_service.start_resume_builder_session(
            access_token="access" if auth_context else "",
            refresh_token="refresh" if auth_context else "",
        )


# ─── resume_parses enforcement ──────────────────────────────────────────


def test_4th_resume_parse_on_free_returns_429(stub_resume_parser):
    """Free's resume_parses cap is 3. The 4th parse rejects with
    cap=3 and current=3."""
    auth_context = _build_auth_context(user_id="user-free-parse-1")
    for _ in range(TIER_CAPS["free"]["resume_parses"]):
        result = _parse(auth_context=auth_context)
        assert "resume_document" in result

    with pytest.raises(QuotaExceededError) as exc_info:
        _parse(auth_context=auth_context)
    err = exc_info.value
    assert err.counter == "resume_parses"
    assert err.cap == TIER_CAPS["free"]["resume_parses"] == 3
    assert err.current == 3
    assert err.reset_period == current_period_key()
    assert err.tier == "free"


def test_26th_resume_parse_on_pro_returns_429(stub_resume_parser, monkeypatch):
    """Pro's resume_parses cap is 25. The 26th parse rejects."""
    monkeypatch.setattr(workspace_service, "resolve_user_tier", lambda _u: "pro")
    auth_context = _build_auth_context(user_id="user-pro-parse-1")

    for _ in range(TIER_CAPS["pro"]["resume_parses"]):
        _parse(auth_context=auth_context)

    with pytest.raises(QuotaExceededError) as exc_info:
        _parse(auth_context=auth_context)
    err = exc_info.value
    assert err.counter == "resume_parses"
    assert err.cap == TIER_CAPS["pro"]["resume_parses"] == 25
    assert err.current == 25
    assert err.tier == "pro"


def test_parse_pipeline_failure_refunds_the_counter(stub_resume_parser, monkeypatch):
    """parse_resume_document raising must roll the resume_parses
    counter back so the user can retry without losing a credit.
    """
    auth_context = _build_auth_context(user_id="user-free-parse-refund-1")

    boom = RuntimeError("corrupted upload")
    monkeypatch.setattr(
        workspace_service,
        "parse_resume_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(boom),
    )
    with pytest.raises(RuntimeError, match="corrupted upload"):
        _parse(auth_context=auth_context)

    # Restore the happy path and confirm the user still has the full
    # free-tier allowance (3 parses) -- not 2, which would be the
    # case if the failed attempt had consumed a credit.
    from src.schemas import ResumeDocument

    monkeypatch.setattr(
        workspace_service,
        "parse_resume_document",
        lambda _fh, source=None: ResumeDocument(
            text="resume", filetype="TXT", source="workspace:test"
        ),
    )
    for _ in range(3):
        _parse(auth_context=auth_context)
    with pytest.raises(QuotaExceededError):
        _parse(auth_context=auth_context)


def test_anonymous_parse_bypasses_the_gate(stub_resume_parser):
    """No auth -> no user_id -> gate skipped. Parsing still works."""
    result = _parse(auth_context=None)
    assert "resume_document" in result


# ─── resume_builder_sessions enforcement ────────────────────────────────


def test_2nd_resume_builder_session_on_free_rejects(monkeypatch):
    """Free's resume_builder_sessions cap is 1 LIFETIME. The first
    session lands, the second rejects with cap=1 and current=1.
    """
    auth_context = _build_auth_context(user_id="user-free-builder-1")

    first = _start_builder(auth_context=auth_context)
    assert first["session_id"]

    with pytest.raises(QuotaExceededError) as exc_info:
        _start_builder(auth_context=auth_context)
    err = exc_info.value
    assert err.counter == "resume_builder_sessions"
    assert err.cap == TIER_CAPS["free"]["resume_builder_sessions"] == 1
    assert err.current == 1
    assert err.reset_period == LIFETIME_PERIOD_KEY  # Free => lifetime
    assert err.tier == "free"


def test_4th_resume_builder_session_on_pro_rejects(monkeypatch):
    """Pro's resume_builder_sessions cap is 3 MONTHLY. Three sessions
    succeed; the 4th rejects.
    """
    monkeypatch.setattr(resume_builder_service, "resolve_user_tier", lambda _u: "pro")
    auth_context = _build_auth_context(user_id="user-pro-builder-1")

    for _ in range(TIER_CAPS["pro"]["resume_builder_sessions"]):
        result = _start_builder(auth_context=auth_context)
        assert result["session_id"]

    with pytest.raises(QuotaExceededError) as exc_info:
        _start_builder(auth_context=auth_context)
    err = exc_info.value
    assert err.counter == "resume_builder_sessions"
    assert err.cap == TIER_CAPS["pro"]["resume_builder_sessions"] == 3
    assert err.current == 3
    # Pro uses the monthly period_key, NOT "lifetime".
    assert err.reset_period == current_period_key()
    assert err.tier == "pro"


def test_free_uses_lifetime_partition_pro_uses_monthly(monkeypatch):
    """Free's session credit lives under period_key=='lifetime'; Pro's
    lives under YYYY-MM. We verify by:
      1. Burning Free's lifetime credit (user A).
      2. Forcing the resolver to "pro" and confirming user A still
         has all 3 monthly credits available (the lifetime and
         monthly rows are separate keys in the backend).
    """
    auth_context = _build_auth_context(user_id="user-mixed-tier-1")

    # Step 1: consume the Free lifetime slot.
    _start_builder(auth_context=auth_context)
    with pytest.raises(QuotaExceededError) as free_err:
        _start_builder(auth_context=auth_context)
    assert free_err.value.reset_period == LIFETIME_PERIOD_KEY

    # Step 2: pretend this same user upgraded. Pro slots are
    # accounted in the YYYY-MM partition, NOT the lifetime one --
    # so the user still has all 3 monthly slots fresh.
    monkeypatch.setattr(resume_builder_service, "resolve_user_tier", lambda _u: "pro")
    for _ in range(TIER_CAPS["pro"]["resume_builder_sessions"]):
        _start_builder(auth_context=auth_context)
    with pytest.raises(QuotaExceededError) as pro_err:
        _start_builder(auth_context=auth_context)
    assert pro_err.value.reset_period == current_period_key()
    assert pro_err.value.tier == "pro"


def test_session_creation_failure_refunds_the_counter(monkeypatch):
    """If the in-memory session insert raises we must roll the credit
    back. Use a Pro user so we have headroom to verify both the
    pre-failure state and the post-refund state.
    """
    monkeypatch.setattr(resume_builder_service, "resolve_user_tier", lambda _u: "pro")
    auth_context = _build_auth_context(user_id="user-pro-builder-refund-1")

    # Boom on the dict mutation only (we patch __setitem__ on the
    # module-level _SESSIONS).
    original_dict = resume_builder_service._SESSIONS

    class _BoomDict(dict):
        def __setitem__(self, _key, _value):
            raise RuntimeError("disk full")

    monkeypatch.setattr(resume_builder_service, "_SESSIONS", _BoomDict())

    with pytest.raises(RuntimeError, match="disk full"):
        _start_builder(auth_context=auth_context)

    # Restore the real dict and confirm we still have all 3 monthly
    # slots available (the failed creation refunded its credit).
    monkeypatch.setattr(resume_builder_service, "_SESSIONS", original_dict)
    for _ in range(TIER_CAPS["pro"]["resume_builder_sessions"]):
        _start_builder(auth_context=auth_context)
    with pytest.raises(QuotaExceededError):
        _start_builder(auth_context=auth_context)


def test_anonymous_start_bypasses_the_gate():
    """No auth -> no user_id -> gate skipped. Session is still
    created and the session_id comes back."""
    result = _start_builder(auth_context=None)
    assert result["session_id"]
