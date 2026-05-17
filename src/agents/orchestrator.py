import logging
import time
from typing import Callable, Optional

from src.errors import AgentExecutionError, OpenAIUnavailableError
from src.logging_utils import get_logger, log_event
from src.openai_service import OpenAIService
from src.schemas import (
    AgentWorkflowResult,
    CandidateProfile,
    JobDescription,
    JobAgentOutput,
    ProfileAgentOutput,
)
from src.services.fit_service import build_fit_analysis
from src.services.tailoring_service import build_tailored_resume_draft

from .cover_letter_agent import CoverLetterAgent
from .resume_generation_agent import ResumeGenerationAgent
from .review_agent import ReviewAgent
from .tailoring_agent import TailoringAgent


LOGGER = get_logger(__name__)


ProgressCallback = Callable[[str, str, int], None]


# User-facing banner copy per provider-failure category. Honest and
# cause-accurate: a real outage blames OpenAI; a rate-limit tells the
# user to retry shortly; a misconfig stays GENERIC (it's our key /
# model bug — don't publicly blame OpenAI; the operator gets the loud
# `orchestrator_openai_misconfigured` ERROR log instead).
_OUTAGE_USER_MESSAGE = {
    "outage": (
        "Our AI provider (OpenAI) is having a moment, so we built a "
        "baseline version of your application. Re-run in a few minutes "
        "for the full AI-tailored result."
    ),
    "rate_limited": (
        "OpenAI is rate-limiting us right now, so we built a baseline "
        "version of your application. Try again in a minute for the "
        "full AI-tailored result."
    ),
    "misconfigured": (
        "AI assistance is temporarily unavailable, so we built a "
        "baseline version of your application. Please try again shortly."
    ),
}


class ApplicationOrchestrator:
    def __init__(
        self,
        openai_service=None,
        allow_fallback=True,
        max_revision_passes=1,
        *,
        model_overrides: Optional[dict] = None,
    ):
        self._openai_service = openai_service or OpenAIService()
        self._allow_fallback = allow_fallback
        self._max_revision_passes = max(0, int(max_revision_passes))
        # Per-task model overrides for tier-aware premium routing.
        # Keyed by agent task name ("tailoring", "review",
        # "resume_generation", "cover_letter"); values are either an
        # explicit model name (e.g. "gpt-5.5") or None / missing,
        # which means "use the standard model for this task". The
        # workspace service computes this map via
        # `backend.model_routing.build_workflow_model_overrides`
        # before calling .run(). Defaults to {} so existing callers
        # (tests, eval scripts) work unchanged.
        self._model_overrides = dict(model_overrides or {})

    def run(
        self,
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis=None,
        tailored_draft=None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> AgentWorkflowResult:
        if fit_analysis is None:
            fit_analysis = build_fit_analysis(candidate_profile, job_description)
        if tailored_draft is None:
            tailored_draft = build_tailored_resume_draft(
                candidate_profile,
                job_description,
                fit_analysis,
            )

        self._emit_progress(
            progress_callback,
            "Workflow crew",
            "Opening your application brief and assigning the first agent.",
            3,
        )

        attempted_assisted = False
        fallback_reason = ""
        fallback_details = ""
        service_unavailable = False

        if self._openai_service.is_available():
            attempted_assisted = True
            policy_label = (
                self._openai_service.describe_model_policy()
                if hasattr(self._openai_service, "describe_model_policy")
                else self._openai_service.model
            )
            try:
                return self._run_pipeline(
                    candidate_profile,
                    job_description,
                    fit_analysis,
                    tailored_draft,
                    openai_service=self._openai_service,
                    mode="openai",
                    model_name=policy_label,
                    max_revision_passes=self._max_revision_passes,
                    attempted_assisted=True,
                    progress_callback=progress_callback,
                    model_overrides=self._model_overrides,
                )
            except AgentExecutionError as exc:
                # Defensive residual. The normal provider-failure path
                # is the circuit breaker INSIDE _run_pipeline (keeps
                # succeeded agents, degrades the rest, returns a
                # flagged result — no exception escapes). We only reach
                # here if _run_pipeline genuinely raised: a content
                # AgentExecutionError whose per-agent fallback ALSO
                # failed, or (shouldn't happen) an OpenAIUnavailableError
                # from a step with no fallback runner. Still flag the
                # outage subclass so even this edge stays honest.
                service_unavailable = isinstance(exc, OpenAIUnavailableError)
                fallback_details = exc.details or ""
                if service_unavailable:
                    fallback_reason = (
                        "Our AI provider (OpenAI) is having a moment, so we "
                        "built a baseline version of your application. Re-run "
                        "in a few minutes for the full AI-tailored result."
                    )
                else:
                    fallback_reason = exc.user_message
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "orchestrator_openai_fallback",
                    "OpenAI orchestration failed; falling back to deterministic mode.",
                    model=policy_label,
                    max_revision_passes=self._max_revision_passes,
                    service_unavailable=service_unavailable,
                    fallback_reason=fallback_reason,
                    fallback_details=fallback_details,
                )
                if not self._allow_fallback:
                    raise

                self._emit_progress(
                    progress_callback,
                    "Backup workflow",
                    "One AI agent hit a snag, so the deterministic backup crew is stepping in.",
                    10,
                )

        return self._run_pipeline(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            openai_service=None,
            mode="deterministic_fallback",
            model_name="fallback",
            max_revision_passes=self._max_revision_passes,
            attempted_assisted=attempted_assisted,
            fallback_reason=fallback_reason,
            fallback_details=fallback_details,
            service_unavailable=service_unavailable,
            progress_callback=progress_callback,
            model_overrides=self._model_overrides,
        )

    @staticmethod
    def _emit_progress(progress_callback, title, detail, value):
        if progress_callback is None:
            return
        progress_callback(title, detail, max(0, min(100, int(value))))

    @staticmethod
    def _run_pipeline(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        openai_service,
        mode,
        model_name,
        max_revision_passes=1,
        attempted_assisted=False,
        fallback_reason="",
        fallback_details="",
        service_unavailable=False,
        progress_callback: Optional[ProgressCallback] = None,
        model_overrides: Optional[dict] = None,
    ):
        # `model_overrides` is keyed by agent task name and carries an
        # explicit model string (e.g. "gpt-5.5") or None when the
        # standard task-routed model should win. Missing keys are
        # treated as None — the agents themselves default to the
        # task_name lookup when `model_override` is None.
        overrides = model_overrides or {}
        tailoring_agent = TailoringAgent(
            openai_service,
            model_override=overrides.get("tailoring"),
        )
        review_agent = ReviewAgent(
            openai_service,
            model_override=overrides.get("review"),
        )
        cover_letter_agent = CoverLetterAgent(
            openai_service,
            model_override=overrides.get("cover_letter"),
        )

        final_tailoring_output = None
        review_output = None
        resume_generation_output = None
        cover_letter_output = None
        total_stage_count = 5
        stage_index = 0

        # Per-agent outcome counters. The orchestrator was previously
        # all-or-nothing — one failing agent meant the whole pipeline
        # downgraded to deterministic. With the per-agent fallback
        # path that's no longer true, but we still need to know
        # whether ANY agent used the LLM so the result.mode honestly
        # reflects what happened. A run where every agent fell back
        # per-agent shouldn't claim to be "openai".
        #
        # `first_llm_error` captures the first AgentExecutionError
        # that triggered a per-agent fallback. If reconciliation at
        # the end of the pipeline flips mode to deterministic_fallback
        # (i.e. zero llm successes), we surface this error's
        # user_message + details as the fallback_reason — preserving
        # the contract that consumers reading fallback_reason get the
        # specific exception message that caused the downgrade.
        agent_outcomes = {
            "llm_success_count": 0,
            "per_agent_fallback_count": 0,
            "first_llm_error": None,
        }

        # Circuit breaker for PROVIDER-level failures (outage /
        # rate-limit / misconfig). Once one agent hits an
        # OpenAIUnavailableError that survived the SDK+app retries, the
        # wall is pipeline-wide — every later agent would hit it too.
        # We do NOT tear the run down (agents that already succeeded on
        # the LLM keep their output); instead we open the breaker so
        # the remaining agents skip straight to their deterministic
        # fallback (no wasted retries hammering a down/limited/broken
        # provider) and the result is flagged with the specific
        # category so the UI shows an honest, cause-accurate notice.
        outage_state = {"tripped": False, "category": "", "error": None}

        def stage_progress(current_stage_index):
            if total_stage_count <= 1:
                return 95
            return 5 + int(round(((current_stage_index - 1) / (total_stage_count - 1)) * 90))

        def begin_stage(title, detail):
            nonlocal stage_index
            stage_index += 1
            ApplicationOrchestrator._emit_progress(
                progress_callback,
                title,
                detail,
                stage_progress(stage_index),
            )

        def run_agent_step(
            agent_name,
            runner,
            *,
            deterministic_fallback_runner=None,
            **context,
        ):
            # Three-tier failure handling per agent:
            #
            # 1. Try `runner()` (the LLM path). If it succeeds, done.
            # 2. If it raises AgentExecutionError, retry once after
            #    a small delay. If the retry succeeds, done.
            # 3. If the retry ALSO fails AND a deterministic fallback
            #    runner is provided, run that and return its output —
            #    keeping the rest of the pipeline running on LLM. This
            #    is the per-agent fallback isolation: previously, one
            #    failing agent cascaded to "downgrade the whole run
            #    to deterministic" — including agents that would have
            #    succeeded on the LLM path. Now only the failing
            #    agent's output is deterministic; downstream agents
            #    still try the LLM.
            #
            # The retry + per-agent fallback both fire only in
            # mode="openai". In deterministic mode the agents skip the
            # LLM path internally so retry/fallback never trigger.
            #
            # Only AgentExecutionError is retried/fallback'd. Other
            # exceptions (bugs, contract violations) propagate
            # immediately — they wouldn't change on retry.

            # Circuit OPEN: a prior agent already hit a provider-level
            # failure. The wall is pipeline-wide, so don't make the
            # user wait while THIS agent also burns SDK+app retries
            # against a down/limited/misconfigured provider — go
            # straight to its deterministic fallback. Agents that
            # already succeeded on the LLM (earlier in the sequence)
            # are untouched; we never throw good work away.
            if (
                outage_state["tripped"]
                and mode == "openai"
                and deterministic_fallback_runner is not None
            ):
                agent_outcomes["per_agent_fallback_count"] += 1
                log_event(
                    LOGGER,
                    logging.INFO,
                    "agent_run_circuit_open",
                    "Provider circuit open from an earlier agent; skipping the LLM for this agent and using its deterministic fallback.",
                    agent=agent_name,
                    mode=mode,
                    model=model_name,
                    outage_category=outage_state["category"],
                    **context,
                )
                return deterministic_fallback_runner()

            agent_retry_delay_seconds = 0.4
            started_at = time.perf_counter()
            last_exc = None
            for attempt_index in range(2):
                attempt_started_at = time.perf_counter()
                try:
                    result = runner()
                except OpenAIUnavailableError as exc:
                    # PROVIDER-level failure that survived SDK+app
                    # retries. Trip the breaker (so the remaining
                    # agents skip the LLM) and give THIS agent its
                    # deterministic fallback. We do NOT retry it (the
                    # provider is down/limited/misconfigured — another
                    # attempt won't help and a 429 only gets worse) and
                    # we do NOT tear down agents that already succeeded.
                    category = getattr(exc, "category", "outage") or "outage"
                    if not outage_state["tripped"]:
                        outage_state["tripped"] = True
                        outage_state["category"] = category
                        outage_state["error"] = exc
                    log_event(
                        LOGGER,
                        logging.ERROR if category == "misconfigured" else logging.WARNING,
                        "orchestrator_openai_misconfigured"
                        if category == "misconfigured"
                        else "agent_run_provider_unavailable",
                        "AI provider failure during agent run; opening the circuit and using deterministic fallback for this and remaining agents.",
                        agent=agent_name,
                        mode=mode,
                        model=model_name,
                        outage_category=category,
                        duration_ms=round(
                            (time.perf_counter() - started_at) * 1000, 2
                        ),
                        error_type=type(exc).__name__,
                        details=exc.details or "",
                        **context,
                    )
                    if mode == "openai" and deterministic_fallback_runner is not None:
                        if agent_outcomes["first_llm_error"] is None:
                            agent_outcomes["first_llm_error"] = exc
                        agent_outcomes["per_agent_fallback_count"] += 1
                        return deterministic_fallback_runner()
                    # No per-agent fallback available — let it cascade
                    # to run()'s outer handler (whole-pipeline
                    # deterministic), which still flags the outage.
                    raise
                except AgentExecutionError as exc:
                    last_exc = exc
                    if attempt_index == 0 and mode == "openai":
                        log_event(
                            LOGGER,
                            logging.WARNING,
                            "agent_run_retry",
                            "Agent run failed; retrying once before falling back.",
                            agent=agent_name,
                            mode=mode,
                            model=model_name,
                            attempt_duration_ms=round(
                                (time.perf_counter() - attempt_started_at) * 1000,
                                2,
                            ),
                            error_type=type(exc).__name__,
                            details=exc.details or "",
                            retry_delay_seconds=agent_retry_delay_seconds,
                            **context,
                        )
                        time.sleep(agent_retry_delay_seconds)
                        continue
                    # Both LLM attempts exhausted. If a per-agent
                    # deterministic fallback was provided, run it
                    # for THIS agent only; the rest of the pipeline
                    # keeps trying the LLM path.
                    if (
                        mode == "openai"
                        and deterministic_fallback_runner is not None
                    ):
                        log_event(
                            LOGGER,
                            logging.WARNING,
                            "agent_run_per_agent_fallback",
                            "LLM attempts exhausted for this agent; using its deterministic fallback. Other agents continue with the LLM path.",
                            agent=agent_name,
                            mode=mode,
                            model=model_name,
                            llm_duration_ms=round(
                                (time.perf_counter() - started_at) * 1000, 2
                            ),
                            llm_attempts=attempt_index + 1,
                            error_type=type(exc).__name__,
                            details=exc.details or "",
                            **context,
                        )
                        try:
                            fallback_result = deterministic_fallback_runner()
                        except Exception as fb_exc:
                            # The per-agent deterministic fallback
                            # itself failed — that's our own code, not
                            # the LLM. Log and re-raise the original
                            # LLM error so the orchestrator's outer
                            # try/except catches it and falls back to
                            # the whole-pipeline deterministic path
                            # (the existing safety net).
                            log_event(
                                LOGGER,
                                logging.ERROR,
                                "agent_run_failed",
                                "Per-agent deterministic fallback also failed; cascading to whole-pipeline fallback.",
                                agent=agent_name,
                                mode=mode,
                                model=model_name,
                                duration_ms=round(
                                    (time.perf_counter() - started_at) * 1000, 2
                                ),
                                llm_attempts=attempt_index + 1,
                                fallback_error_type=type(fb_exc).__name__,
                                fallback_details=str(fb_exc),
                                **context,
                            )
                            raise
                        agent_outcomes["per_agent_fallback_count"] += 1
                        if agent_outcomes["first_llm_error"] is None:
                            agent_outcomes["first_llm_error"] = exc
                        log_event(
                            LOGGER,
                            logging.INFO,
                            "agent_run_completed",
                            "Agent run completed via per-agent deterministic fallback.",
                            agent=agent_name,
                            mode=mode,
                            model=model_name,
                            duration_ms=round(
                                (time.perf_counter() - started_at) * 1000, 2
                            ),
                            llm_attempts=attempt_index + 1,
                            fell_back_to_deterministic=True,
                            **context,
                        )
                        return fallback_result
                    # No per-agent fallback runner provided (or we're
                    # in deterministic mode). Cascade up.
                    log_event(
                        LOGGER,
                        logging.ERROR,
                        "agent_run_failed",
                        "Agent run failed (after assisted-mode retry).",
                        agent=agent_name,
                        mode=mode,
                        model=model_name,
                        duration_ms=round(
                            (time.perf_counter() - started_at) * 1000, 2
                        ),
                        attempts=attempt_index + 1,
                        error_type=type(exc).__name__,
                        **context,
                    )
                    raise
                except Exception as exc:
                    # Non-AgentExecutionError exceptions (bugs in our
                    # code, contract violations, etc.) — retrying
                    # won't change the outcome. Log and re-raise
                    # immediately.
                    log_event(
                        LOGGER,
                        logging.ERROR,
                        "agent_run_failed",
                        "Agent run failed with unexpected exception.",
                        agent=agent_name,
                        mode=mode,
                        model=model_name,
                        duration_ms=round(
                            (time.perf_counter() - started_at) * 1000, 2
                        ),
                        attempts=attempt_index + 1,
                        error_type=type(exc).__name__,
                        **context,
                    )
                    raise
                # Success path. If this was the second attempt, the
                # retry saved the run — reflect that in the log so we
                # can see how often it actually pays off.
                #
                # Only count toward llm_success when the pipeline is
                # actually in assisted mode. In deterministic mode the
                # agent's own internal fallback ran (no LLM call), so
                # crediting it as an LLM success would mislead the
                # mode-reconciliation logic at the end of the pipeline.
                if mode == "openai":
                    agent_outcomes["llm_success_count"] += 1
                log_event(
                    LOGGER,
                    logging.INFO,
                    "agent_run_completed",
                    "Agent run completed.",
                    agent=agent_name,
                    mode=mode,
                    model=model_name,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    attempts=attempt_index + 1,
                    recovered_via_retry=attempt_index > 0,
                    **context,
                )
                return result
            # Unreachable: every iteration of the loop either returns
            # or raises. Defensive raise so a future edit can't silently
            # produce None.
            raise last_exc if last_exc else AgentExecutionError(
                "Agent run exited the retry loop without producing a result."
            )

        # Matchmaker agent: the deterministic build_fit_analysis() above
        # already computed matched/missing skills, score, and grounded
        # gaps + recommendations. No LLM step needed here — TailoringAgent
        # reads the structured FitAnalysis directly. Keep the stage label
        # so the UI progress indicator still renders the matchmaker step.
        begin_stage(
            "Matchmaker agent",
            "Comparing both sides, scoring overlap, and flagging the real gaps.",
        )

        begin_stage(
            "Forge agent",
            "Rewriting the draft so it speaks directly to this role.",
        )
        # Each call site supplies a deterministic_fallback_runner that
        # constructs a fresh agent instance with openai_service=None.
        # The agent classes already short-circuit to their internal
        # _fallback() when no service is configured (see e.g.
        # TailoringAgent.run's `if self._openai_service` gate), so this
        # gives us the deterministic output for THIS agent only.
        # Downstream agents still try the LLM path on the values
        # produced here — exactly the per-agent isolation we want.
        tailoring_output = run_agent_step(
            "tailoring",
            lambda: tailoring_agent.run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
            ),
            deterministic_fallback_runner=lambda: TailoringAgent(None).run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
            ),
        )
        begin_stage(
            "Gatekeeper agent",
            "Reviewing the drafted outputs and applying grounded corrections.",
        )
        review_output = run_agent_step(
            "review",
            lambda: review_agent.run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                tailoring_output,
            ),
            deterministic_fallback_runner=lambda: ReviewAgent(None).run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                tailoring_output,
            ),
        )
        final_tailoring_output = review_output.corrected_tailoring or tailoring_output

        begin_stage(
            "Builder agent",
            "Packaging the final tailored resume and lining up the finish.",
        )
        resume_generation_output = run_agent_step(
            "resume_generation",
            lambda: ResumeGenerationAgent(
                openai_service,
                model_override=overrides.get("resume_generation"),
            ).run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                final_tailoring_output,
                review_output,
            ),
            deterministic_fallback_runner=lambda: ResumeGenerationAgent(None).run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                final_tailoring_output,
                review_output,
            ),
            review_approved=review_output.approved if review_output else False,
        )

        begin_stage(
            "Cover letter agent",
            "Turning the approved story into a role-specific cover letter that is ready to send.",
        )
        if review_output and review_output.approved:
            cover_letter_output = run_agent_step(
                "cover_letter",
                lambda: cover_letter_agent.run(
                    candidate_profile,
                    job_description,
                    fit_analysis,
                    tailored_draft,
                    final_tailoring_output,
                    review_output,
                    resume_generation_output,
                ),
                deterministic_fallback_runner=lambda: CoverLetterAgent(None).run(
                    candidate_profile,
                    job_description,
                    fit_analysis,
                    tailored_draft,
                    final_tailoring_output,
                    review_output,
                    resume_generation_output,
                ),
                review_approved=True,
            )

        # Reconcile the reported mode with what actually happened. If
        # the pipeline was started as openai but every single agent
        # fell back per-agent (zero llm_success_count), the run was
        # functionally deterministic — pretending it was "openai"
        # would mislead consumers that watch the mode field. Flip
        # mode AND model to the deterministic-fallback values in
        # that case, and surface the first LLM error as the
        # fallback_reason (preserves the historical contract that
        # whole-pipeline-fallback consumers read).
        reported_mode = mode
        reported_model = model_name
        reported_fallback_reason = fallback_reason
        reported_fallback_details = fallback_details
        if (
            mode == "openai"
            and agent_outcomes["llm_success_count"] == 0
            and agent_outcomes["per_agent_fallback_count"] > 0
        ):
            reported_mode = "deterministic_fallback"
            reported_model = "fallback"
            first_error = agent_outcomes["first_llm_error"]
            if first_error is not None:
                if not reported_fallback_reason:
                    reported_fallback_reason = first_error.user_message
                if not reported_fallback_details:
                    reported_fallback_details = first_error.details or ""
            if not reported_fallback_reason:
                reported_fallback_reason = (
                    "Every assisted agent fell back to deterministic output."
                )

        # A provider-level failure (breaker tripped anywhere in the
        # run) ALWAYS flags the result + rewrites the reason with the
        # cause-accurate banner copy — even when some agents still
        # succeeded on the LLM (reported_mode stays "openai" in that
        # partial case; the banner tells the user some sections used a
        # fallback and to re-run). `service_unavailable` from the
        # caller (run()'s defensive cascade path) is OR-ed in.
        final_service_unavailable = bool(
            service_unavailable or outage_state["tripped"]
        )
        if outage_state["tripped"]:
            outage_category = outage_state["category"] or "outage"
            reported_fallback_reason = _OUTAGE_USER_MESSAGE.get(
                outage_category, _OUTAGE_USER_MESSAGE["outage"]
            )
            outage_error = outage_state["error"]
            if outage_error is not None:
                reported_fallback_details = (
                    getattr(outage_error, "details", "") or ""
                )

        log_event(
            LOGGER,
            logging.INFO,
            "orchestrator_completed",
            "Application orchestration completed.",
            mode=reported_mode,
            model=reported_model,
            review_passes=1,
            approved=review_output.approved if review_output else False,
            llm_success_count=agent_outcomes["llm_success_count"],
            per_agent_fallback_count=agent_outcomes["per_agent_fallback_count"],
            service_unavailable=final_service_unavailable,
            outage_category=outage_state["category"],
        )

        ApplicationOrchestrator._emit_progress(
            progress_callback,
            "Workflow crew",
            "All agents are done. Finalizing your application outputs.",
            100,
        )

        return AgentWorkflowResult(
            mode=reported_mode,
            model=reported_model,
            tailoring=final_tailoring_output,
            review=review_output,
            profile=ProfileAgentOutput(),
            job=JobAgentOutput(),
            strategy=None,
            resume_generation=resume_generation_output,
            cover_letter=cover_letter_output,
            review_history=[],
            attempted_assisted=attempted_assisted,
            fallback_reason=reported_fallback_reason,
            fallback_details=reported_fallback_details,
            # True when the circuit breaker tripped (provider outage /
            # rate-limit / misconfig) anywhere in the run, OR the
            # caller's defensive cascade flagged it. A content-only
            # per-agent downgrade leaves this False.
            service_unavailable=final_service_unavailable,
        )
