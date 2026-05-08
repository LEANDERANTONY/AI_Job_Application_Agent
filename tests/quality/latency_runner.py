"""Exhaustive latency-baseline runner.

Measures p50 / p95 / p99 of every backend endpoint plus the agentic
LLM chain. Mirrors the structure of the other tests/quality/*_runner.py
scripts: deterministic vs --include-llm, JSON scorecard at
``tests/quality/_last_latency_run.json``, console table sorted by
p95 desc.

Per the plan in docs/LATENCY-TEST-PLAN.md:

- Tier 1 (deterministic): always runs. Cheap. ~30s wall clock.
- Tier 2 (LLM-gated, --include-llm): single LLM calls per scenario.
- Tier 3 (LLM-gated, --include-llm): per-agent + full orchestrator.

Each scenario reports cold (single first-hit on a fresh app) plus
N warm samples. Per-scenario p95 is checked against budgets:

- PASS  if actual_p95 <= budget_p95
- WARN  if budget_p95 < actual_p95 <= 1.5 * budget_p95
- FAIL  if actual_p95 >  1.5 * budget_p95

Exit 0 if no FAILs (warns are advisory). Exit 1 if any FAIL.

Usage:
    python tests/quality/latency_runner.py
    python tests/quality/latency_runner.py --include-llm
    python tests/quality/latency_runner.py --include-llm --json out.json
    python tests/quality/latency_runner.py --include-live
    python tests/quality/latency_runner.py --tier 1
"""
from __future__ import annotations

import argparse
import base64
import importlib
import json
import os
import sys
import time
import traceback
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Make the worktree's repo root importable. Direct script invocation
# bypasses pyproject.toml's pytest pythonpath, so `import backend`
# would otherwise fail. Insert before stdlib so the worktree wins
# over any sibling install.
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Permissive rate limit BEFORE backend.app loads slowapi.
# The default LIMIT_HEAVY budget is 10/minute, which trips on a 10-warm
# burst. We're measuring latency, not the limiter — bypass it.
# ---------------------------------------------------------------------------

os.environ["RATE_LIMIT_OVERRIDE"] = "100000/minute"


# ---------------------------------------------------------------------------
# Paths + constants
# ---------------------------------------------------------------------------

QUALITY_DIR = REPO_ROOT / "tests" / "quality"
SAMPLE_RESUME_PATH = QUALITY_DIR / "sample_resumes" / "02-midcareer-tech.txt"
SAMPLE_JD_PATH = QUALITY_DIR / "sample_jds" / "07-placer-big-data-engineer.txt"
DEFAULT_JSON_PATH = QUALITY_DIR / "_last_latency_run.json"

# Tier-tuned warm-run counts. Tier-1 is cheap (no LLM). Tier-2/3 LLM
# scenarios cost real OpenAI dollars — keep N small to stay near the
# plan's ~$0.50-per-run estimate.
N_WARM_TIER_1 = 10
N_WARM_TIER_2 = 3
N_WARM_TIER_3 = 2
N_WARM_TIER_2_HEAVY = 1  # full orchestrator end-to-end


# ---------------------------------------------------------------------------
# Mock infrastructure: auth + Supabase stores + thread-job worker
#
# Latency is about code-path, not network — mocks so the runner doesn't
# need real Supabase round-trips. The error-handling chat is doing the
# same kind of mocking; their changes shouldn't conflict because we
# patch by import-target, not by editing the modules themselves.
# ---------------------------------------------------------------------------


_FAKE_USER_ID = "00000000-0000-0000-0000-000000000000"
_FAKE_ACCESS_TOKEN = "latency-runner-fake-access-token"
_FAKE_REFRESH_TOKEN = "latency-runner-fake-refresh-token"
_FAKE_AUTH_HEADERS = {
    "X-Auth-Access-Token": _FAKE_ACCESS_TOKEN,
    "X-Auth-Refresh-Token": _FAKE_REFRESH_TOKEN,
}


def _fake_app_user():
    return SimpleNamespace(
        id=_FAKE_USER_ID,
        email="latency-runner@example.com",
        plan_tier="free",
        avatar_url="",
        display_name="Latency Runner",
        created_at="",
        last_seen_at="",
        account_status="active",
    )


def _fake_auth_session():
    return SimpleNamespace(
        access_token=_FAKE_ACCESS_TOKEN,
        refresh_token=_FAKE_REFRESH_TOKEN,
        user=SimpleNamespace(
            user_id=_FAKE_USER_ID,
            email="latency-runner@example.com",
            display_name="Latency Runner",
            avatar_url="",
        ),
    )


class _FakeAuthContext:
    def __init__(self):
        self.auth_service = SimpleNamespace()
        self.auth_session = _fake_auth_session()
        self.app_user = _fake_app_user()
        self.daily_quota = None


def _fake_resolve_authenticated_context(*, access_token, refresh_token):
    return _FakeAuthContext()


class _FakeSavedWorkspaceRecord:
    def __init__(self, job_title="Test Role"):
        self.job_title = job_title
        self.expires_at = "2030-01-01T00:00:00Z"
        self.updated_at = "2030-01-01T00:00:00Z"


class _FakeSavedWorkspaceStore:
    def __init__(self, auth_service):
        pass

    def is_configured(self):
        return True

    def save_workspace(self, access_token, refresh_token, payload):
        return _FakeSavedWorkspaceRecord(
            job_title=str(payload.get("job_title", "Test Role")),
        )

    # Returning None / "missing" means /workspace/saved short-circuits
    # to "no saved workspace yet" — quickest path through the route.
    def load_workspace(self, access_token, refresh_token, user_id):
        return None, "missing"


class _FakeSavedJobsStore:
    def __init__(self, auth_service):
        pass

    def is_configured(self):
        return True

    def list_jobs(self, access_token, refresh_token, user_id):
        return []

    def save_job(self, access_token, refresh_token, payload):
        return dict(payload)

    def delete_job(self, access_token, refresh_token, user_id, job_id):
        return None


class _FakeResumeBuilderStore:
    def __init__(self, auth_service):
        pass

    def is_configured(self):
        return True

    def save_session(self, access_token, refresh_token, payload):
        return SimpleNamespace(expires_at="2030-01-01T00:00:00Z")

    def load_latest_session(self, access_token, refresh_token, user_id):
        return None

    def delete_session(self, access_token, refresh_token, user_id):
        return None


class _FakeCachedJobsStore:
    """Used by /workspace/saved-jobs to annotate listing-status.
    Return is_configured=False so the annotation pass is skipped."""

    def __init__(self, *args, **kwargs):
        pass

    def is_configured(self):
        return False

    def get_listing_status_map(self, keys):
        return {}


_SHARED_OPENAI_SERVICE: Any | None = None


def _shared_openai_service():
    """Lazy-construct one OpenAIService and reuse it for every LLM run.
    Saves the per-call HTTP client setup cost; mirrors the convention
    in tests/quality/orchestrator_e2e_runner.py."""
    global _SHARED_OPENAI_SERVICE
    if _SHARED_OPENAI_SERVICE is None:
        from src.openai_service import OpenAIService

        _SHARED_OPENAI_SERVICE = OpenAIService()
    return _SHARED_OPENAI_SERVICE


def _fake_build_openai_service_for_context(context):
    return _shared_openai_service(), None


def _fake_run_workspace_analysis_for_thread(
    *,
    resume_text,
    resume_filetype,
    resume_source,
    job_description_text,
    imported_job_posting,
    run_assisted,
    access_token="",
    refresh_token="",
    progress_callback=None,
):
    """Background thread spawned by /workspace/analyze-jobs runs the FULL
    assisted workflow (4 LLM agents, ~$0.50 a pop). For the start /
    poll endpoints we only care about the spawn + dict-read cost, not
    the agent work. Patch the worker function to a fast no-op so the
    threadpool doesn't burn budget under us during Tier-1 measurement."""
    if progress_callback is not None:
        progress_callback("Workflow crew", "Latency-runner stub.", 100)
    return {
        "resume_document": {"text": resume_text, "filetype": resume_filetype, "source": resume_source},
        "candidate_profile": {},
        "job_description": {},
        "jd_summary_view": {},
        "fit_analysis": {},
        "tailored_draft": {},
        "agent_result": None,
        "artifacts": {"tailored_resume": {}, "cover_letter": {}},
        "workflow": {
            "mode": "deterministic_preview",
            "assisted_requested": False,
            "assisted_available": False,
            "review_approved": False,
            "fallback_reason": "",
        },
        "imported_job_posting": imported_job_posting,
    }


@contextmanager
def _force_openai_unavailable():
    """For Tier 1 scenarios. Several routes labeled "deterministic" in
    the plan (resume parser, JD parser, /workspace/analyze deterministic,
    resume-builder/commit) actually run LLM-first with deterministic
    fallback on failure. To get an honest deterministic baseline, force
    `OpenAIService.is_available()` to False for the duration — every
    LLM-first wrapper short-circuits to its regex/heuristic path."""
    def _noop(self):
        return False

    with patch(
        "src.openai_service.OpenAIService.is_available",
        _noop,
    ):
        yield


@contextmanager
def _nullcontext():
    yield


@contextmanager
def _persistence_mocks():
    """Patch every Supabase-touching surface used by the routes we
    measure. Plus stub the analyze-jobs thread worker so Tier-1 doesn't
    indirectly burn LLM budget through the spawned thread.

    Patches are by import-target, not by editing modules — keeps us
    isolated from the parallel error-handling chat.
    """
    targets_resolve = [
        "backend.services.workspace_persistence_service.resolve_authenticated_context",
        "backend.services.saved_jobs_service.resolve_authenticated_context",
        "backend.services.resume_builder_persistence_service.resolve_authenticated_context",
        "backend.services.workspace_service.resolve_authenticated_context",
        "backend.routers.workspace.resolve_authenticated_context",
    ]
    targets_build_openai = [
        "backend.routers.workspace.build_openai_service_for_context",
        "backend.services.workspace_service.build_openai_service_for_context",
    ]
    with ExitStack() as stack:
        for tgt in targets_resolve:
            stack.enter_context(patch(tgt, _fake_resolve_authenticated_context))
        for tgt in targets_build_openai:
            stack.enter_context(
                patch(tgt, _fake_build_openai_service_for_context)
            )
        stack.enter_context(
            patch(
                "backend.services.workspace_persistence_service.SavedWorkspaceStore",
                _FakeSavedWorkspaceStore,
            )
        )
        stack.enter_context(
            patch(
                "backend.services.saved_jobs_service.SavedJobsStore",
                _FakeSavedJobsStore,
            )
        )
        stack.enter_context(
            patch(
                "backend.services.saved_jobs_service.CachedJobsStore",
                _FakeCachedJobsStore,
            )
        )
        stack.enter_context(
            patch(
                "backend.services.resume_builder_persistence_service.ResumeBuilderStore",
                _FakeResumeBuilderStore,
            )
        )
        stack.enter_context(
            patch(
                "backend.services.workspace_run_jobs.run_workspace_analysis",
                _fake_run_workspace_analysis_for_thread,
            )
        )
        yield


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


def _drop_process_local_state():
    """Reset _SESSIONS / _JOBS dicts so cold measurements aren't polluted
    by previous scenarios in the same process."""
    try:
        from backend.services import resume_builder_service

        resume_builder_service._SESSIONS.clear()
    except Exception:
        pass
    try:
        from backend.services import workspace_run_jobs

        workspace_run_jobs._JOBS.clear()
    except Exception:
        pass


def _make_fresh_app():
    """Reload backend.app so module-level lru_caches start empty.
    Returns a TestClient bound to the fresh app instance.

    Caveat: Python's import cache for transitive deps stays warm.
    Cold here means 'first hit on a fresh FastAPI instance', not
    'fresh interpreter'. The plan accepts this.
    """
    from fastapi.testclient import TestClient

    _drop_process_local_state()
    import backend.app as backend_app_module

    importlib.reload(backend_app_module)
    return TestClient(backend_app_module.app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _read_fixture(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"Fixture missing: {path}")
    return path.read_text(encoding="utf-8")


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def _build_workspace_snapshot(client, *, resume_text: str, jd_text: str):
    """Run /workspace/analyze deterministic to get a real, valid snapshot
    we can replay through /save, /artifacts/export, /artifacts/preview,
    and /assistant/answer. Cached across scenarios in a single run."""
    response = client.post(
        "/api/workspace/analyze",
        json={
            "resume_text": resume_text,
            "resume_filetype": "TXT",
            "resume_source": "latency-runner",
            "job_description_text": jd_text,
            "imported_job_posting": None,
            "run_assisted": False,
        },
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "candidate_profile": payload["candidate_profile"],
        "job_description": payload["job_description"],
        "fit_analysis": payload["fit_analysis"],
        "tailored_draft": payload["tailored_draft"],
        "agent_result": payload.get("agent_result"),
        "artifacts": payload["artifacts"],
        "imported_job_posting": payload.get("imported_job_posting"),
    }


def _build_resume_builder_session(client) -> str:
    """Walk the resume-builder regex flow to ready-to-generate so we have
    a session_id usable by /commit and /export."""
    start = client.post(
        "/api/workspace/resume-builder/start",
        headers=_FAKE_AUTH_HEADERS,
    )
    start.raise_for_status()
    session_id = start.json()["session_id"]

    intake = [
        "Leander Antony\nChennai, India\nleander@example.com\n+91 9999999999\nlinkedin.com/in/leander",
        "Machine Learning Engineer\nAI engineer with product-focused ML experience.",
        "AI Engineer at Example Labs\nJan 2023 - Present\nBuilt ML APIs.\nImproved evaluation workflows.",
        "Anna University | B.E. Computer Science\nAWS Certified Machine Learning Specialty",
        "Python, FastAPI, Docker, LLMs, SQL",
    ]
    for message in intake:
        r = client.post(
            "/api/workspace/resume-builder/message",
            json={
                "session_id": session_id,
                "message": message,
                "input_mode": "text",
            },
        )
        r.raise_for_status()
    return session_id


def _build_agent_inputs():
    """Same fixture pair the e2e orchestrator runner uses
    (02-midcareer-tech.txt, 07-placer-big-data-engineer.txt). Run the
    deterministic profile/JD/fit/draft prep once and reuse for every
    Tier-3 scenario invocation."""
    from src.schemas import ResumeDocument
    from src.services.fit_service import build_fit_analysis
    from src.services.job_service import build_job_description_from_text
    from src.services.profile_service import (
        build_candidate_profile_from_resume_auto,
    )
    from src.services.tailoring_service import build_tailored_resume_draft

    resume_text = _read_fixture(SAMPLE_RESUME_PATH)
    jd_text = _read_fixture(SAMPLE_JD_PATH)

    document = ResumeDocument(text=resume_text, filetype="TXT", source=str(SAMPLE_RESUME_PATH))
    candidate_profile = build_candidate_profile_from_resume_auto(document)
    job_description = build_job_description_from_text(jd_text)
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile, job_description, fit_analysis
    )
    return {
        "candidate_profile": candidate_profile,
        "job_description": job_description,
        "fit_analysis": fit_analysis,
        "tailored_draft": tailored_draft,
    }


# ---------------------------------------------------------------------------
# Scenario shape
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    tier: int
    requires_llm: bool
    p50_budget_ms: float
    p95_budget_ms: float
    n_warm: int
    # Setup runs once per scenario, before the cold measurement.
    # Returns whatever fixture data the run-fn needs.
    setup: Optional[Callable[..., Any]] = None
    # For Tier 1 + Tier 2 (HTTP via TestClient): (client, fixture) -> None
    fn_http: Optional[Callable[..., None]] = None
    # For Tier 3 (in-process agents): (openai_service, agent_inputs) -> None
    fn_agent: Optional[Callable[..., None]] = None
    # /jobs/search?live=true is slow on purpose; skip unless --include-live.
    skip_unless_live: bool = False
    # Skip cold measurement for routes where the cold metric is
    # dominated by setup, not the route itself (e.g., resume-builder
    # commit reuses an already-warm session).
    skip_cold: bool = False


@dataclass
class ScenarioResult:
    name: str
    tier: int
    requires_llm: bool
    cold_ms: Optional[float]
    warm_ms: list[float]
    p50_ms: float
    p95_ms: float
    p99_ms: float
    p50_budget_ms: float
    p95_budget_ms: float
    status: str
    note: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Scenario factories
# ---------------------------------------------------------------------------


def _scenario_factories(args, resume_text: str, jd_text: str) -> list[Scenario]:
    # ----- Tier 1 (deterministic) -----------------------------------------
    tier1: list[Scenario] = []

    tier1.append(Scenario(
        name="GET /api/health",
        tier=1, requires_llm=False, p50_budget_ms=50, p95_budget_ms=100,
        n_warm=N_WARM_TIER_1,
        fn_http=lambda client, _fixture: client.get("/api/health").raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/jobs/search (cached, simple)",
        tier=1, requires_llm=False, p50_budget_ms=500, p95_budget_ms=1500,
        n_warm=N_WARM_TIER_1,
        fn_http=lambda client, _fixture: client.post(
            "/api/jobs/search", json={"query": "engineer"},
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/jobs/search (cached, with filters)",
        tier=1, requires_llm=False, p50_budget_ms=800, p95_budget_ms=2000,
        n_warm=N_WARM_TIER_1,
        fn_http=lambda client, _fixture: client.post(
            "/api/jobs/search",
            json={
                "query": "machine learning",
                "work_mode": "remote",
                "employment_type": "full_time",
                "sort_by": "newest",
            },
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/jobs/search?live=true (live fan-out)",
        tier=1, requires_llm=False, p50_budget_ms=30000, p95_budget_ms=45000,
        n_warm=2,  # live fan-out is genuinely slow; don't run 10 of them
        skip_unless_live=True,
        fn_http=lambda client, _fixture: client.post(
            "/api/jobs/search?live=true",
            json={"query": "engineer"},
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/resume/upload (TXT)",
        tier=1, requires_llm=False, p50_budget_ms=500, p95_budget_ms=1500,
        n_warm=N_WARM_TIER_1,
        setup=lambda client: {"payload": {
            "filename": "resume.txt",
            "mime_type": "text/plain",
            "content_base64": _b64(resume_text),
        }},
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/resume/upload", json=fixture["payload"],
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/job-description/upload (TXT)",
        tier=1, requires_llm=False, p50_budget_ms=500, p95_budget_ms=1500,
        n_warm=N_WARM_TIER_1,
        setup=lambda client: {"payload": {
            "filename": "jd.txt",
            "mime_type": "text/plain",
            "content_base64": _b64(jd_text),
        }},
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/job-description/upload", json=fixture["payload"],
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/analyze (deterministic)",
        tier=1, requires_llm=False, p50_budget_ms=500, p95_budget_ms=1500,
        n_warm=N_WARM_TIER_1,
        setup=lambda client: {"payload": {
            "resume_text": resume_text,
            "resume_filetype": "TXT",
            "resume_source": "latency-runner",
            "job_description_text": jd_text,
            "imported_job_posting": None,
            "run_assisted": False,
        }},
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/analyze", json=fixture["payload"],
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/analyze-jobs (start)",
        tier=1, requires_llm=False, p50_budget_ms=100, p95_budget_ms=200,
        n_warm=N_WARM_TIER_1,
        setup=lambda client: {"payload": {
            "resume_text": resume_text,
            "resume_filetype": "TXT",
            "resume_source": "latency-runner",
            "job_description_text": jd_text,
            "imported_job_posting": None,
            "run_assisted": True,
        }},
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/analyze-jobs",
            json=fixture["payload"],
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    def _setup_analyze_job_id(client):
        # Start one job we can poll N times. The threaded worker is
        # mocked, so it completes effectively instantly.
        r = client.post(
            "/api/workspace/analyze-jobs",
            json={
                "resume_text": resume_text,
                "resume_filetype": "TXT",
                "resume_source": "latency-runner",
                "job_description_text": jd_text,
                "imported_job_posting": None,
                "run_assisted": True,
            },
            headers=_FAKE_AUTH_HEADERS,
        )
        r.raise_for_status()
        return {"job_id": r.json()["job_id"]}

    tier1.append(Scenario(
        name="GET /api/workspace/analyze-jobs/{id} (poll)",
        tier=1, requires_llm=False, p50_budget_ms=100, p95_budget_ms=200,
        n_warm=N_WARM_TIER_1,
        setup=_setup_analyze_job_id,
        fn_http=lambda client, fixture: client.get(
            f"/api/workspace/analyze-jobs/{fixture['job_id']}",
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/resume-builder/start",
        tier=1, requires_llm=False, p50_budget_ms=200, p95_budget_ms=500,
        n_warm=N_WARM_TIER_1,
        fn_http=lambda client, _fixture: client.post(
            "/api/workspace/resume-builder/start",
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    def _setup_builder_session(client):
        return {"session_id": _build_resume_builder_session(client)}

    tier1.append(Scenario(
        name="POST /api/workspace/resume-builder/commit",
        tier=1, requires_llm=False, p50_budget_ms=500, p95_budget_ms=1000,
        n_warm=1,  # commit is one-shot; subsequent calls 400 (session cleared)
        skip_cold=True,
        setup=_setup_builder_session,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/resume-builder/commit",
            json={"session_id": fixture["session_id"]},
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/resume-builder/export (DOCX)",
        tier=1, requires_llm=False, p50_budget_ms=300, p95_budget_ms=600,
        n_warm=N_WARM_TIER_1,
        setup=_setup_builder_session,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/resume-builder/export",
            json={
                "session_id": fixture["session_id"],
                "export_format": "docx",
                "theme": "classic_ats",
            },
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/resume-builder/export (PDF)",
        tier=1, requires_llm=False, p50_budget_ms=1500, p95_budget_ms=4000,
        n_warm=3,  # WeasyPrint is heavy; 3 samples is enough
        setup=_setup_builder_session,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/resume-builder/export",
            json={
                "session_id": fixture["session_id"],
                "export_format": "pdf",
                "theme": "classic_ats",
            },
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    def _setup_workspace_snapshot(client):
        return {"snapshot": _build_workspace_snapshot(
            client, resume_text=resume_text, jd_text=jd_text,
        )}

    tier1.append(Scenario(
        name="POST /api/workspace/artifacts/export (DOCX)",
        tier=1, requires_llm=False, p50_budget_ms=300, p95_budget_ms=600,
        n_warm=N_WARM_TIER_1,
        setup=_setup_workspace_snapshot,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/artifacts/export",
            json={
                "workspace_snapshot": fixture["snapshot"],
                "artifact_kind": "tailored_resume",
                "export_format": "docx",
                "resume_theme": "classic_ats",
                "cover_letter_theme": "classic_ats",
            },
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/artifacts/export (PDF)",
        tier=1, requires_llm=False, p50_budget_ms=1500, p95_budget_ms=4000,
        n_warm=3,
        setup=_setup_workspace_snapshot,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/artifacts/export",
            json={
                "workspace_snapshot": fixture["snapshot"],
                "artifact_kind": "tailored_resume",
                "export_format": "pdf",
                "resume_theme": "classic_ats",
                "cover_letter_theme": "classic_ats",
            },
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/artifacts/preview (resume HTML)",
        tier=1, requires_llm=False, p50_budget_ms=200, p95_budget_ms=500,
        n_warm=N_WARM_TIER_1,
        setup=_setup_workspace_snapshot,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/artifacts/preview",
            json={
                "workspace_snapshot": fixture["snapshot"],
                "artifact_kind": "tailored_resume",
                "resume_theme": "classic_ats",
                "cover_letter_theme": "classic_ats",
            },
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="POST /api/workspace/save (auth + persistence mocked)",
        tier=1, requires_llm=False, p50_budget_ms=500, p95_budget_ms=1500,
        n_warm=N_WARM_TIER_1,
        setup=_setup_workspace_snapshot,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/save",
            json={"workspace_snapshot": fixture["snapshot"]},
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="GET /api/workspace/saved (auth + load mocked)",
        tier=1, requires_llm=False, p50_budget_ms=800, p95_budget_ms=2000,
        n_warm=N_WARM_TIER_1,
        fn_http=lambda client, _fixture: client.get(
            "/api/workspace/saved", headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    tier1.append(Scenario(
        name="GET /api/workspace/saved-jobs (auth + list mocked)",
        tier=1, requires_llm=False, p50_budget_ms=500, p95_budget_ms=1500,
        n_warm=N_WARM_TIER_1,
        fn_http=lambda client, _fixture: client.get(
            "/api/workspace/saved-jobs", headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    # ----- Tier 2 (LLM) ----------------------------------------------------
    tier2: list[Scenario] = []

    tier2.append(Scenario(
        name="POST /api/workspace/resume/upload (LLM hybrid)",
        tier=2, requires_llm=True, p50_budget_ms=8000, p95_budget_ms=12000,
        n_warm=N_WARM_TIER_2,
        setup=lambda client: {"payload": {
            "filename": "resume.txt",
            "mime_type": "text/plain",
            "content_base64": _b64(resume_text),
        }},
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/resume/upload", json=fixture["payload"],
        ).raise_for_status(),
    ))

    def _setup_builder_message(client):
        session_id = _build_resume_builder_session(client)
        return {"session_id": session_id}

    tier2.append(Scenario(
        name="POST /api/workspace/resume-builder/message (LLM)",
        tier=2, requires_llm=True, p50_budget_ms=3000, p95_budget_ms=5000,
        n_warm=N_WARM_TIER_2,
        setup=_setup_builder_message,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/resume-builder/message",
            json={
                "session_id": fixture["session_id"],
                "message": "Add another bullet about ML evaluation tooling.",
                "input_mode": "text",
            },
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    tier2.append(Scenario(
        name="POST /api/workspace/resume-builder/generate",
        tier=2, requires_llm=True, p50_budget_ms=10000, p95_budget_ms=20000,
        n_warm=N_WARM_TIER_2,
        setup=_setup_builder_session,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/resume-builder/generate",
            json={"session_id": fixture["session_id"]},
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    def _build_assistant_payload(snapshot):
        return {
            "question": "What stands out about my fit for this role?",
            "current_page": "Workspace",
            "workspace_snapshot": snapshot,
            "history": [],
        }

    tier2.append(Scenario(
        name="POST /api/workspace/assistant/answer (LLM, sync)",
        tier=2, requires_llm=True, p50_budget_ms=3000, p95_budget_ms=6000,
        n_warm=N_WARM_TIER_2,
        setup=_setup_workspace_snapshot,
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/assistant/answer",
            json=_build_assistant_payload(fixture["snapshot"]),
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    def _stream_ttft(client, fixture):
        with client.stream(
            "POST",
            "/api/workspace/assistant/answer/stream",
            json=_build_assistant_payload(fixture["snapshot"]),
            headers=_FAKE_AUTH_HEADERS,
        ) as resp:
            for line in resp.iter_lines():
                if line.startswith("event: delta"):
                    return
                if line.startswith("event: error"):
                    return  # error path still produces a measurable first byte

    def _stream_total(client, fixture):
        with client.stream(
            "POST",
            "/api/workspace/assistant/answer/stream",
            json=_build_assistant_payload(fixture["snapshot"]),
            headers=_FAKE_AUTH_HEADERS,
        ) as resp:
            for line in resp.iter_lines():
                if line.startswith("event: done"):
                    return

    tier2.append(Scenario(
        name="POST /api/workspace/assistant/answer/stream (TTFT)",
        tier=2, requires_llm=True, p50_budget_ms=1500, p95_budget_ms=2500,
        n_warm=N_WARM_TIER_2,
        setup=_setup_workspace_snapshot,
        fn_http=_stream_ttft,
    ))

    tier2.append(Scenario(
        name="POST /api/workspace/assistant/answer/stream (total)",
        tier=2, requires_llm=True, p50_budget_ms=5000, p95_budget_ms=10000,
        n_warm=N_WARM_TIER_2,
        setup=_setup_workspace_snapshot,
        fn_http=_stream_total,
    ))

    tier2.append(Scenario(
        name="POST /api/workspace/analyze (assisted, full chain)",
        tier=2, requires_llm=True, p50_budget_ms=60000, p95_budget_ms=120000,
        n_warm=N_WARM_TIER_2_HEAVY,
        setup=lambda client: {"payload": {
            "resume_text": resume_text,
            "resume_filetype": "TXT",
            "resume_source": "latency-runner",
            "job_description_text": jd_text,
            "imported_job_posting": None,
            "run_assisted": True,
        }},
        fn_http=lambda client, fixture: client.post(
            "/api/workspace/analyze",
            json=fixture["payload"],
            headers=_FAKE_AUTH_HEADERS,
        ).raise_for_status(),
    ))

    # ----- Tier 3 (per-agent isolation, in-process) -----------------------
    tier3: list[Scenario] = []

    def _run_tailoring(openai_service, agent_inputs):
        from src.agents.tailoring_agent import TailoringAgent

        TailoringAgent(openai_service).run(
            agent_inputs["candidate_profile"],
            agent_inputs["job_description"],
            agent_inputs["fit_analysis"],
            agent_inputs["tailored_draft"],
        )

    def _run_review(openai_service, agent_inputs):
        from src.agents.review_agent import ReviewAgent
        from src.agents.tailoring_agent import TailoringAgent

        # Review needs a tailoring_output upstream. Cache it on the
        # agent_inputs dict the first time so subsequent warm runs
        # don't re-burn a TailoringAgent call here.
        cached = agent_inputs.get("_tailoring_output_cached")
        if cached is None:
            cached = TailoringAgent(openai_service).run(
                agent_inputs["candidate_profile"],
                agent_inputs["job_description"],
                agent_inputs["fit_analysis"],
                agent_inputs["tailored_draft"],
            )
            agent_inputs["_tailoring_output_cached"] = cached
        ReviewAgent(openai_service).run(
            agent_inputs["candidate_profile"],
            agent_inputs["job_description"],
            agent_inputs["fit_analysis"],
            agent_inputs["tailored_draft"],
            cached,
        )

    def _run_resume_generation(openai_service, agent_inputs):
        from src.agents.resume_generation_agent import ResumeGenerationAgent
        from src.agents.review_agent import ReviewAgent
        from src.agents.tailoring_agent import TailoringAgent

        tailoring = agent_inputs.get("_tailoring_output_cached")
        review = agent_inputs.get("_review_output_cached")
        if tailoring is None:
            tailoring = TailoringAgent(openai_service).run(
                agent_inputs["candidate_profile"],
                agent_inputs["job_description"],
                agent_inputs["fit_analysis"],
                agent_inputs["tailored_draft"],
            )
            agent_inputs["_tailoring_output_cached"] = tailoring
        if review is None:
            review = ReviewAgent(openai_service).run(
                agent_inputs["candidate_profile"],
                agent_inputs["job_description"],
                agent_inputs["fit_analysis"],
                agent_inputs["tailored_draft"],
                tailoring,
            )
            agent_inputs["_review_output_cached"] = review
        ResumeGenerationAgent(openai_service).run(
            agent_inputs["candidate_profile"],
            agent_inputs["job_description"],
            agent_inputs["fit_analysis"],
            agent_inputs["tailored_draft"],
            review.corrected_tailoring or tailoring,
            review,
        )

    def _run_cover_letter(openai_service, agent_inputs):
        from src.agents.cover_letter_agent import CoverLetterAgent
        from src.agents.resume_generation_agent import ResumeGenerationAgent
        from src.agents.review_agent import ReviewAgent
        from src.agents.tailoring_agent import TailoringAgent

        tailoring = agent_inputs.get("_tailoring_output_cached")
        review = agent_inputs.get("_review_output_cached")
        resume_gen = agent_inputs.get("_resume_gen_cached")
        if tailoring is None:
            tailoring = TailoringAgent(openai_service).run(
                agent_inputs["candidate_profile"],
                agent_inputs["job_description"],
                agent_inputs["fit_analysis"],
                agent_inputs["tailored_draft"],
            )
            agent_inputs["_tailoring_output_cached"] = tailoring
        if review is None:
            review = ReviewAgent(openai_service).run(
                agent_inputs["candidate_profile"],
                agent_inputs["job_description"],
                agent_inputs["fit_analysis"],
                agent_inputs["tailored_draft"],
                tailoring,
            )
            agent_inputs["_review_output_cached"] = review
        final_tailoring = review.corrected_tailoring or tailoring
        if resume_gen is None:
            resume_gen = ResumeGenerationAgent(openai_service).run(
                agent_inputs["candidate_profile"],
                agent_inputs["job_description"],
                agent_inputs["fit_analysis"],
                agent_inputs["tailored_draft"],
                final_tailoring,
                review,
            )
            agent_inputs["_resume_gen_cached"] = resume_gen
        CoverLetterAgent(openai_service).run(
            agent_inputs["candidate_profile"],
            agent_inputs["job_description"],
            agent_inputs["fit_analysis"],
            agent_inputs["tailored_draft"],
            final_tailoring,
            review,
            resume_gen,
        )

    def _run_full_orchestrator(openai_service, agent_inputs):
        from src.agents.orchestrator import ApplicationOrchestrator

        ApplicationOrchestrator(openai_service=openai_service).run(
            agent_inputs["candidate_profile"],
            agent_inputs["job_description"],
            fit_analysis=agent_inputs["fit_analysis"],
            tailored_draft=agent_inputs["tailored_draft"],
        )

    tier3.append(Scenario(
        name="TailoringAgent (isolated, mid-trust mini)",
        tier=3, requires_llm=True, p50_budget_ms=8000, p95_budget_ms=15000,
        n_warm=N_WARM_TIER_3,
        fn_agent=_run_tailoring,
    ))
    tier3.append(Scenario(
        name="ReviewAgent (isolated, high-trust)",
        tier=3, requires_llm=True, p50_budget_ms=8000, p95_budget_ms=18000,
        n_warm=N_WARM_TIER_3,
        fn_agent=_run_review,
    ))
    tier3.append(Scenario(
        name="ResumeGenerationAgent (isolated, high-trust)",
        tier=3, requires_llm=True, p50_budget_ms=10000, p95_budget_ms=20000,
        n_warm=N_WARM_TIER_3,
        fn_agent=_run_resume_generation,
    ))
    tier3.append(Scenario(
        name="CoverLetterAgent (isolated, high-trust)",
        tier=3, requires_llm=True, p50_budget_ms=8000, p95_budget_ms=18000,
        n_warm=N_WARM_TIER_3,
        fn_agent=_run_cover_letter,
    ))
    tier3.append(Scenario(
        name="Full orchestrator chain (4 agents in sequence)",
        tier=3, requires_llm=True, p50_budget_ms=35000, p95_budget_ms=70000,
        n_warm=N_WARM_TIER_2_HEAVY,
        fn_agent=_run_full_orchestrator,
    ))

    return tier1 + tier2 + tier3


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def _percentiles(samples: list[float]) -> tuple[float, float, float]:
    if not samples:
        return 0.0, 0.0, 0.0
    sorted_s = sorted(samples)
    n = len(sorted_s)

    def pct(p: float) -> float:
        if n == 1:
            return sorted_s[0]
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return sorted_s[idx]

    return pct(0.5), pct(0.95), pct(0.99)


def _classify(p95_actual_ms: float, p95_budget_ms: float) -> str:
    if p95_actual_ms <= p95_budget_ms:
        return "PASS"
    if p95_actual_ms <= 1.5 * p95_budget_ms:
        return "WARN"
    return "FAIL"


def _measure_one(fn, *args) -> float:
    t0 = time.perf_counter()
    fn(*args)
    return (time.perf_counter() - t0) * 1000.0


def _run_http_scenario(scenario: Scenario) -> ScenarioResult:
    """Tier 1 + Tier 2 scenarios. Fresh app per scenario for honest cold."""
    error_text = ""
    try:
        client = _make_fresh_app()
        fixture = scenario.setup(client) if scenario.setup else None
        cold_ms: Optional[float] = None
        if not scenario.skip_cold:
            cold_ms = _measure_one(scenario.fn_http, client, fixture)
        warm_ms: list[float] = []
        for _ in range(scenario.n_warm):
            warm_ms.append(_measure_one(scenario.fn_http, client, fixture))
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        return ScenarioResult(
            name=scenario.name, tier=scenario.tier,
            requires_llm=scenario.requires_llm, cold_ms=None, warm_ms=[],
            p50_ms=0, p95_ms=0, p99_ms=0,
            p50_budget_ms=scenario.p50_budget_ms,
            p95_budget_ms=scenario.p95_budget_ms,
            status="FAIL", error=error_text,
        )

    p50, p95, p99 = _percentiles(warm_ms)
    return ScenarioResult(
        name=scenario.name, tier=scenario.tier,
        requires_llm=scenario.requires_llm, cold_ms=cold_ms, warm_ms=warm_ms,
        p50_ms=p50, p95_ms=p95, p99_ms=p99,
        p50_budget_ms=scenario.p50_budget_ms,
        p95_budget_ms=scenario.p95_budget_ms,
        status=_classify(p95, scenario.p95_budget_ms),
    )


def _run_agent_scenario(scenario: Scenario, agent_inputs) -> ScenarioResult:
    """Tier 3: in-process agent calls. Reuses one OpenAIService."""
    error_text = ""
    try:
        openai_service = _shared_openai_service()
        cold_ms = _measure_one(scenario.fn_agent, openai_service, agent_inputs)
        warm_ms = []
        for _ in range(scenario.n_warm):
            warm_ms.append(_measure_one(scenario.fn_agent, openai_service, agent_inputs))
    except Exception as exc:
        error_text = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        return ScenarioResult(
            name=scenario.name, tier=scenario.tier,
            requires_llm=scenario.requires_llm, cold_ms=None, warm_ms=[],
            p50_ms=0, p95_ms=0, p99_ms=0,
            p50_budget_ms=scenario.p50_budget_ms,
            p95_budget_ms=scenario.p95_budget_ms,
            status="FAIL", error=error_text,
        )

    p50, p95, p99 = _percentiles(warm_ms)
    return ScenarioResult(
        name=scenario.name, tier=scenario.tier,
        requires_llm=scenario.requires_llm, cold_ms=cold_ms, warm_ms=warm_ms,
        p50_ms=p50, p95_ms=p95, p99_ms=p99,
        p50_budget_ms=scenario.p50_budget_ms,
        p95_budget_ms=scenario.p95_budget_ms,
        status=_classify(p95, scenario.p95_budget_ms),
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "    -"
    if value >= 1000:
        return f"{value / 1000:>6.2f}s"
    return f"{value:>7.0f}ms"


def _print_table(results: list[ScenarioResult]) -> None:
    rows = sorted(results, key=lambda r: r.p95_ms, reverse=True)
    print()
    print("=" * 110)
    print("Latency scorecard (sorted by p95 desc)")
    print("=" * 110)
    print(
        f"{'Scenario':<60}  {'cold':>9}  {'p50':>9}  {'p95':>9}  "
        f"{'p99':>9}  {'budget95':>9}  status"
    )
    print("-" * 110)
    for r in rows:
        print(
            f"{r.name[:60]:<60}  "
            f"{_fmt_ms(r.cold_ms):>9}  "
            f"{_fmt_ms(r.p50_ms):>9}  "
            f"{_fmt_ms(r.p95_ms):>9}  "
            f"{_fmt_ms(r.p99_ms):>9}  "
            f"{_fmt_ms(r.p95_budget_ms):>9}  "
            f"{r.status}"
            + (f"  ({r.error})" if r.error else "")
        )
    print("-" * 110)


def _to_json_payload(
    results: list[ScenarioResult],
    *,
    include_llm: bool,
    args_summary: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "total_scenarios": len(results),
        "passed": sum(1 for r in results if r.status == "PASS"),
        "warned": sum(1 for r in results if r.status == "WARN"),
        "failed": sum(1 for r in results if r.status == "FAIL"),
    }
    return {
        "ran_with_llm": include_llm,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "args": args_summary,
        "scenarios": [
            {
                "name": r.name,
                "tier": r.tier,
                "requires_llm": r.requires_llm,
                "cold_ms": round(r.cold_ms, 2) if r.cold_ms is not None else None,
                "samples_warm_ms": [round(v, 2) for v in r.warm_ms],
                "p50_ms": round(r.p50_ms, 2),
                "p95_ms": round(r.p95_ms, 2),
                "p99_ms": round(r.p99_ms, 2),
                "p50_budget_ms": r.p50_budget_ms,
                "p95_budget_ms": r.p95_budget_ms,
                "status": r.status,
                "error": r.error or None,
            }
            for r in results
        ],
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-llm", action="store_true",
        help="Run Tier 2 + Tier 3 scenarios. Costs ~$0.50 in OpenAI tokens.",
    )
    parser.add_argument(
        "--include-live", action="store_true",
        help="Include /jobs/search?live=true (live fan-out, ~30s).",
    )
    parser.add_argument(
        "--tier", type=int, choices=[1, 2, 3], default=None,
        help="Run only this tier (default: 1, plus 2 + 3 if --include-llm).",
    )
    parser.add_argument(
        "--json", type=Path, default=DEFAULT_JSON_PATH,
        help="JSON scorecard output path.",
    )
    args = parser.parse_args()

    print("=" * 78)
    print("Latency baseline runner")
    print(
        f"include-llm={args.include_llm}  "
        f"include-live={args.include_live}  "
        f"tier-filter={args.tier or 'all'}"
    )
    print("=" * 78)

    resume_text = _read_fixture(SAMPLE_RESUME_PATH)
    jd_text = _read_fixture(SAMPLE_JD_PATH)

    started_at = time.perf_counter()
    results: list[ScenarioResult] = []
    agent_inputs_cache: dict[str, Any] | None = None

    with _persistence_mocks():
        scenarios = _scenario_factories(args, resume_text, jd_text)
        for scenario in scenarios:
            if args.tier and scenario.tier != args.tier:
                continue
            if scenario.requires_llm and not args.include_llm:
                continue
            if scenario.skip_unless_live and not args.include_live:
                continue

            print(f"\n>>> [{scenario.tier}] {scenario.name}")
            # Tier 1 + any non-LLM scenario: force OpenAI off so
            # LLM-first parsers/services short-circuit deterministic.
            llm_gate = (
                _nullcontext() if scenario.requires_llm else _force_openai_unavailable()
            )
            with llm_gate:
                if scenario.fn_http is not None:
                    result = _run_http_scenario(scenario)
                else:
                    if agent_inputs_cache is None:
                        agent_inputs_cache = _build_agent_inputs()
                    result = _run_agent_scenario(scenario, agent_inputs_cache)
            results.append(result)

            cold_str = _fmt_ms(result.cold_ms).strip() if result.cold_ms is not None else "  (skipped)"
            print(
                f"    cold={cold_str}  "
                f"p50={_fmt_ms(result.p50_ms).strip()}  "
                f"p95={_fmt_ms(result.p95_ms).strip()}  "
                f"budget95={_fmt_ms(result.p95_budget_ms).strip()}  "
                f"-> {result.status}"
                + (f"  [{result.error}]" if result.error else "")
            )

    elapsed_s = time.perf_counter() - started_at

    _print_table(results)
    print(f"\nWall clock: {elapsed_s:.1f}s   "
          f"PASS={sum(1 for r in results if r.status == 'PASS')}  "
          f"WARN={sum(1 for r in results if r.status == 'WARN')}  "
          f"FAIL={sum(1 for r in results if r.status == 'FAIL')}")

    payload = _to_json_payload(
        results,
        include_llm=args.include_llm,
        args_summary={
            "include_llm": args.include_llm,
            "include_live": args.include_live,
            "tier": args.tier,
            "wall_clock_seconds": round(elapsed_s, 2),
        },
    )
    args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nScorecard JSON: {args.json}")

    sys.exit(1 if any(r.status == "FAIL" for r in results) else 0)


if __name__ == "__main__":
    main()
