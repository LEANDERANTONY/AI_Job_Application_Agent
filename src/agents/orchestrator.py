import logging
import time
from typing import Callable, Optional

from src.errors import AgentExecutionError
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

from .fit_agent import FitAgent
from .resume_generation_agent import ResumeGenerationAgent
from .review_agent import ReviewAgent
from .strategy_agent import StrategyAgent
from .tailoring_agent import TailoringAgent


LOGGER = get_logger(__name__)


ProgressCallback = Callable[[str, str, int], None]


class ApplicationOrchestrator:
    def __init__(self, openai_service=None, allow_fallback=True, max_revision_passes=1):
        self._openai_service = openai_service or OpenAIService()
        self._allow_fallback = allow_fallback
        self._max_revision_passes = max(0, int(max_revision_passes))

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
                )
            except AgentExecutionError as exc:
                fallback_reason = exc.user_message
                fallback_details = exc.details or ""
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "orchestrator_openai_fallback",
                    "OpenAI orchestration failed; falling back to deterministic mode.",
                    model=policy_label,
                    max_revision_passes=self._max_revision_passes,
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
            progress_callback=progress_callback,
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
        progress_callback: Optional[ProgressCallback] = None,
    ):
        tailoring_agent = TailoringAgent(openai_service)
        review_agent = ReviewAgent(openai_service)
        strategy_agent = StrategyAgent(openai_service)

        final_tailoring_output = None
        final_strategy_output = None
        review_output = None
        resume_generation_output = None
        total_stage_count = 5
        stage_index = 0

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

        def run_agent_step(agent_name, runner, **context):
            started_at = time.perf_counter()
            try:
                result = runner()
            except Exception as exc:
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "agent_run_failed",
                    "Agent run failed.",
                    agent=agent_name,
                    mode=mode,
                    model=model_name,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    error_type=type(exc).__name__,
                    **context,
                )
                raise
            log_event(
                LOGGER,
                logging.INFO,
                "agent_run_completed",
                "Agent run completed.",
                agent=agent_name,
                mode=mode,
                model=model_name,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                **context,
            )
            return result

        begin_stage(
            "Matchmaker agent",
            "Comparing both sides, scoring overlap, and flagging the real gaps.",
        )
        fit_output = run_agent_step(
            "fit",
            lambda: FitAgent(openai_service).run(
                candidate_profile,
                job_description,
                fit_analysis,
            ),
        )

        begin_stage(
            "Forge agent",
            "Rewriting the draft so it speaks directly to this role.",
        )
        tailoring_output = run_agent_step(
            "tailoring",
            lambda: tailoring_agent.run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                fit_output,
            ),
        )
        begin_stage(
            "Navigator agent",
            "Shaping the recruiter story so the pitch lands cleanly.",
        )
        strategy_output = run_agent_step(
            "strategy",
            lambda: strategy_agent.run(
                candidate_profile,
                job_description,
                fit_analysis,
                fit_output,
                tailoring_output,
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
                strategy_output,
            ),
        )
        final_tailoring_output = review_output.corrected_tailoring or tailoring_output
        final_strategy_output = review_output.corrected_strategy or strategy_output

        begin_stage(
            "Builder agent",
            "Packaging the final tailored resume and lining up the finish.",
        )
        resume_generation_output = run_agent_step(
            "resume_generation",
            lambda: ResumeGenerationAgent(openai_service).run(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                final_tailoring_output,
                final_strategy_output,
                review_output,
            ),
            review_approved=review_output.approved if review_output else False,
        )

        log_event(
            LOGGER,
            logging.INFO,
            "orchestrator_completed",
            "Application orchestration completed.",
            mode=mode,
            model=model_name,
            review_passes=1,
            approved=review_output.approved if review_output else False,
        )

        ApplicationOrchestrator._emit_progress(
            progress_callback,
            "Workflow crew",
            "All agents are done. Finalizing your application outputs.",
            100,
        )

        return AgentWorkflowResult(
            mode=mode,
            model=model_name,
            fit=fit_output,
            tailoring=final_tailoring_output,
            review=review_output,
            profile=ProfileAgentOutput(),
            job=JobAgentOutput(),
            strategy=final_strategy_output,
            resume_generation=resume_generation_output,
            review_history=[],
            attempted_assisted=attempted_assisted,
            fallback_reason=fallback_reason,
            fallback_details=fallback_details,
        )
