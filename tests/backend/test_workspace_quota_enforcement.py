"""Quota enforcement at /workspace/analyze (the brief's "/workspace/run").

Step 3 of the tier-enforcement series. The integration tests in
test_backend_workspace.py cover the happy path for the analyze
endpoint already; here we focus on the quota gate specifically:

  * 4th call on Free with premium=False returns 429.
  * 1st call on Free with premium=True returns 429 (Pro+ only).
  * 6th call on Pro with premium=True returns 429.
  * Workflow failure decrements the counter so the user can retry.
  * Anonymous + premium=False bypasses the gate (no user_id to
    attribute the credit to).
  * Anonymous + premium=True still rejects with the Pro+ message.

The tests reach in past the route handler and call
`run_workspace_analysis` directly when they need to inject auth
context or force an orchestrator failure. The end-to-end HTTP layer
is exercised separately to confirm the 429 surface is intact.
"""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import quota
from backend.app import app
from backend.quota import current_period_key, reset_in_memory_backend
from backend.services import workspace_service
from backend.services.auth_session_service import AuthenticatedContext
from backend.tiers import TIER_CAPS
from src.auth_service import AuthUser, AuthSession
from src.errors import QuotaExceededError
from src.schemas import AppUserRecord


client = TestClient(app, raise_server_exceptions=False)


# ─── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_quota_backend(monkeypatch):
    """Force the in-memory quota backend with empty state. autouse so
    every test starts from zero credits across all counters."""

    class _NeverConfigured:
        def is_configured(self) -> bool:
            return False

    monkeypatch.setattr(quota, "_SUPABASE_BACKEND", _NeverConfigured())
    reset_in_memory_backend()
    yield
    reset_in_memory_backend()


def _build_auth_context(*, user_id: str = "user-test", email: str = "u@example.com"):
    """Construct a minimally-valid AuthenticatedContext for the gate.

    The gate only reads `auth_context.app_user.id`. We populate the
    nested fields just enough to satisfy the dataclass constructors --
    nothing downstream of `quota.check_and_increment` reads them in
    these tests because we stub out the pipeline."""
    auth_session = AuthSession(
        access_token="access",
        refresh_token="refresh",
        user=AuthUser(user_id=user_id, email=email),
    )
    app_user = AppUserRecord(id=user_id, email=email)
    return AuthenticatedContext(
        auth_service=None,  # type: ignore[arg-type] - unused in these tests
        auth_session=auth_session,
        app_user=app_user,
        daily_quota=None,
    )


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Replace the expensive parts of run_workspace_analysis so tests
    can focus on the quota gate behavior.

    Stubs:
      * `build_candidate_profile_from_resume_auto` -> a minimal
        CandidateProfile so downstream signatures are happy.
      * `build_job_description_from_text_auto` -> a minimal JD.
      * `build_fit_analysis`, `build_tailored_resume_draft`,
        `generate_job_summary_view`, `build_tailored_resume_artifact`,
        `build_cover_letter_artifact` -> trivial dict-like returns.

    This isolates the quota gate from parser/LLM behavior so a quota
    rejection test never has to construct a full resume corpus.
    """
    from src.schemas import (
        CandidateProfile,
        CoverLetterArtifact,
        FitAnalysis,
        JobDescription,
        JobRequirements,
        TailoredResumeArtifact,
        TailoredResumeDraft,
    )

    profile = CandidateProfile(
        full_name="Test",
        source="test",
        resume_text="",
    )
    jd = JobDescription(
        title="Test Role",
        raw_text="jd",
        cleaned_text="jd",
        requirements=JobRequirements(),
    )
    fit = FitAnalysis(
        target_role="Test Role",
        overall_score=80,
        readiness_label="Promising",
    )
    draft = TailoredResumeDraft(
        target_role="Test Role",
        professional_summary="",
    )
    # generate_job_summary_view returns a plain dict; the workspace
    # service serializes whatever it gets so a dict round-trips fine.
    summary = {"mode": "deterministic", "sections": []}

    tailored_artifact = TailoredResumeArtifact(
        title="Tailored Resume",
        filename_stem="resume",
        summary="",
        markdown="md",
        plain_text="",
    )
    cover_artifact = CoverLetterArtifact(
        title="Cover Letter",
        filename_stem="cover",
        summary="",
        markdown="md",
        plain_text="",
    )

    monkeypatch.setattr(
        workspace_service,
        "build_candidate_profile_from_resume_auto",
        lambda _doc, **_kwargs: profile,
    )
    monkeypatch.setattr(
        workspace_service,
        "build_job_description_from_text_auto",
        lambda _text, **_kwargs: jd,
    )
    monkeypatch.setattr(
        workspace_service,
        "build_fit_analysis",
        lambda _p, _j: fit,
    )
    monkeypatch.setattr(
        workspace_service,
        "build_tailored_resume_draft",
        lambda _p, _j, _f: draft,
    )
    monkeypatch.setattr(
        workspace_service,
        "generate_job_summary_view",
        lambda **_kwargs: summary,
    )
    monkeypatch.setattr(
        workspace_service,
        "build_tailored_resume_artifact",
        lambda *_args, **_kwargs: tailored_artifact,
    )
    monkeypatch.setattr(
        workspace_service,
        "build_cover_letter_artifact",
        lambda *_args, **_kwargs: cover_artifact,
    )
    # Sidestep the real OpenAI/usage-store wiring -- the tests use a
    # synthetic AuthenticatedContext that doesn't carry a working
    # AuthService, and `build_openai_service_for_context` calls
    # UsageStore.is_configured() through it. Returning (None, None)
    # mirrors the "no LLM available, fall back to deterministic" path
    # the workspace service already supports.
    monkeypatch.setattr(
        workspace_service,
        "build_openai_service_for_context",
        lambda _context: (None, None),
    )


def _run(*, auth_context=None, premium=False, **overrides):
    """Drive `run_workspace_analysis` directly with the stub pipeline.

    Patches `resolve_authenticated_context` to return the supplied
    auth_context without going through Supabase. Returns whatever the
    workspace service returns (or propagates the raised exception).
    """
    monkeypatch_targets: list[tuple[object, str, object]] = []

    def _resolver(*, access_token=None, refresh_token=None):
        return auth_context

    with patch.object(
        workspace_service,
        "resolve_authenticated_context",
        _resolver,
    ):
        return workspace_service.run_workspace_analysis(
            resume_text="Resume body",
            resume_filetype="TXT",
            resume_source="workspace",
            job_description_text="JD body",
            imported_job_posting=None,
            run_assisted=False,
            premium=premium,
            access_token="access" if auth_context else "",
            refresh_token="refresh" if auth_context else "",
            **overrides,
        )


# ─── core enforcement assertions ────────────────────────────────────────


def test_4th_basic_app_on_free_returns_429_via_quota(stub_pipeline):
    """Free tier cap on tailored_applications is 3. Three runs succeed
    (decrementing the counter on the 4th attempt would be 4 > 3),
    the 4th raises QuotaExceededError with cap=3 and current=3.
    """
    auth_context = _build_auth_context(user_id="user-free-1")

    for expected_count in (1, 2, 3):
        result = _run(auth_context=auth_context, premium=False)
        # The workflow's return shape is unchanged; we just need to
        # know it returned successfully N times.
        assert result["workflow"]["mode"] == "deterministic_preview"

    with pytest.raises(QuotaExceededError) as exc_info:
        _run(auth_context=auth_context, premium=False)
    err = exc_info.value
    assert err.counter == "tailored_applications"
    assert err.cap == TIER_CAPS["free"]["tailored_applications"] == 3
    assert err.current == 3
    assert err.reset_period == current_period_key()
    assert err.tier == "free"


def test_free_user_with_premium_true_rejects_on_first_call(stub_pipeline):
    """Free tier's premium_applications cap is 0 -- there is no
    "first run free" loophole. The error message branch surfaces the
    "Pro+ only" copy so the frontend toast can render the upgrade
    nudge instead of a generic "quota exhausted" message.
    """
    auth_context = _build_auth_context(user_id="user-free-2")

    with pytest.raises(QuotaExceededError) as exc_info:
        _run(auth_context=auth_context, premium=True)
    err = exc_info.value
    assert err.counter == "premium_applications"
    assert err.cap == 0
    assert err.current == 0
    assert "Pro" in err.user_message


def test_6th_premium_on_pro_returns_429(stub_pipeline, monkeypatch):
    """Pro's premium_applications cap is 5; the 6th call rejects with
    cap=5 and current=5. The tier is forced to "pro" via a temporary
    override of `resolve_user_tier` because the production shim still
    returns "free" until Stripe lands.
    """
    monkeypatch.setattr(workspace_service, "resolve_user_tier", lambda _u: "pro")
    auth_context = _build_auth_context(user_id="user-pro-1")

    for expected_count in (1, 2, 3, 4, 5):
        _run(auth_context=auth_context, premium=True)

    with pytest.raises(QuotaExceededError) as exc_info:
        _run(auth_context=auth_context, premium=True)
    err = exc_info.value
    assert err.counter == "premium_applications"
    assert err.cap == TIER_CAPS["pro"]["premium_applications"] == 5
    assert err.current == 5
    assert err.tier == "pro"


def test_failed_run_refunds_the_counter(stub_pipeline, monkeypatch):
    """The orchestrator raising mid-workflow must NOT cost the user a
    quota credit. We force one of the deterministic-pipeline steps to
    raise, then verify that the next call still has the same allowance
    a fresh user would have.
    """
    auth_context = _build_auth_context(user_id="user-free-3")

    # First call: increment succeeds, but the artifact step blows up.
    boom = RuntimeError("artifact rendering exploded")
    monkeypatch.setattr(
        workspace_service,
        "build_tailored_resume_artifact",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(boom),
    )

    with pytest.raises(RuntimeError, match="artifact rendering exploded"):
        _run(auth_context=auth_context, premium=False)

    # Refund: counter is back at zero. Restore the artifact builder so
    # the next run is the happy path, then verify three more runs
    # succeed before the cap fires (rather than two, which would be
    # the case if the failed run had still consumed a credit).
    from src.schemas import CoverLetterArtifact, TailoredResumeArtifact

    monkeypatch.setattr(
        workspace_service,
        "build_tailored_resume_artifact",
        lambda *_args, **_kwargs: TailoredResumeArtifact(
            title="Tailored Resume",
            filename_stem="resume",
            summary="",
            markdown="md",
            plain_text="",
        ),
    )
    monkeypatch.setattr(
        workspace_service,
        "build_cover_letter_artifact",
        lambda *_args, **_kwargs: CoverLetterArtifact(
            title="Cover Letter",
            filename_stem="cover",
            summary="",
            markdown="md",
            plain_text="",
        ),
    )

    for _ in range(3):
        _run(auth_context=auth_context, premium=False)
    # The 4th rejects -- matches the "free-tier fresh user" budget,
    # which is the whole point of the refund.
    with pytest.raises(QuotaExceededError) as exc_info:
        _run(auth_context=auth_context, premium=False)
    assert exc_info.value.current == 3


def test_failed_increment_does_not_trigger_refund(stub_pipeline):
    """When the gate itself raises (cap breach), no row was written
    and a refund call would corrupt the count by decrementing somebody
    else's credit. Verify that consecutive failed-attempt cycles don't
    drift the counter."""
    auth_context = _build_auth_context(user_id="user-free-4")

    # Burn the budget.
    for _ in range(3):
        _run(auth_context=auth_context, premium=False)

    # Four rejected attempts in a row.
    for _ in range(4):
        with pytest.raises(QuotaExceededError):
            _run(auth_context=auth_context, premium=False)

    # The counter has not drifted -- still at exactly the cap, not
    # somewhere below it.
    err = None
    try:
        _run(auth_context=auth_context, premium=False)
    except QuotaExceededError as caught:
        err = caught
    assert err is not None
    assert err.current == 3


# ─── anonymous flow ─────────────────────────────────────────────────────


def test_anonymous_basic_run_bypasses_the_gate(stub_pipeline):
    """Anonymous + premium=False: no user_id to attribute the credit
    to, so the gate skips. The deterministic preview still runs (which
    is the current product expectation -- anonymous users get a
    preview without burning a credit).
    """
    result = _run(auth_context=None, premium=False)
    assert result["workflow"]["mode"] == "deterministic_preview"


def test_anonymous_premium_rejects_with_pro_only_message(stub_pipeline):
    """Anonymous + premium=True: there's no user to bill, but premium
    is still a paid feature. Surface the Pro+ message rather than
    silently downgrading the request to a basic run.
    """
    with pytest.raises(QuotaExceededError) as exc_info:
        _run(auth_context=None, premium=True)
    err = exc_info.value
    assert err.counter == "premium_applications"
    assert err.cap == 0
    assert err.tier == "free"
    assert "Pro" in err.user_message


# ─── HTTP surface ───────────────────────────────────────────────────────


def test_route_returns_429_on_quota_exceeded(stub_pipeline, monkeypatch):
    """End-to-end: a Free user at cap hits POST /workspace/analyze and
    gets the canonical 429 payload back. The global handler in
    backend.app converts QuotaExceededError to JSON; the route's
    `except AppError` branch re-raises QuotaExceededError instead of
    catching it (we changed _raise_http_error to special-case quota).
    """
    auth_context = _build_auth_context(user_id="user-http-1")

    monkeypatch.setattr(
        workspace_service,
        "resolve_authenticated_context",
        lambda **_kwargs: auth_context,
    )

    # Burn the budget at the service layer so the route call itself
    # is the one that raises.
    for _ in range(3):
        _run(auth_context=auth_context, premium=False)

    response = client.post(
        "/api/workspace/analyze",
        json={
            "resume_text": "Resume body",
            "resume_filetype": "TXT",
            "resume_source": "workspace",
            "job_description_text": "JD body",
            "run_assisted": False,
            "premium": False,
        },
        headers={
            "X-Auth-Access-Token": "access",
            "X-Auth-Refresh-Token": "refresh",
        },
    )

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "tier_limit_exceeded"
    assert body["counter"] == "tailored_applications"
    assert body["cap"] == 3
    assert body["current"] == 3
    assert body["tier"] == "free"
    assert body["reset_period"] == current_period_key()


def test_route_returns_429_for_free_premium_request(stub_pipeline, monkeypatch):
    """Free user requesting premium=true at the HTTP surface -- the
    "Pro+ only" 429 must come straight back without the route's
    `except AppError` catching it as a generic 400.
    """
    auth_context = _build_auth_context(user_id="user-http-2")
    monkeypatch.setattr(
        workspace_service,
        "resolve_authenticated_context",
        lambda **_kwargs: auth_context,
    )

    response = client.post(
        "/api/workspace/analyze",
        json={
            "resume_text": "Resume body",
            "resume_filetype": "TXT",
            "resume_source": "workspace",
            "job_description_text": "JD body",
            "run_assisted": False,
            "premium": True,
        },
        headers={
            "X-Auth-Access-Token": "access",
            "X-Auth-Refresh-Token": "refresh",
        },
    )

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "tier_limit_exceeded"
    assert body["counter"] == "premium_applications"
    assert body["cap"] == 0
    assert "Pro" in body["detail"]
