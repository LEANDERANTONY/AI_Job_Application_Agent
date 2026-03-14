import logging
import time

from src.errors import AgentExecutionError
from src.logging_utils import get_logger, log_event
from src.openai_service import OpenAIService
from src.schemas import AgentWorkflowResult, CandidateProfile, JobDescription, ReviewPassResult
from src.services.fit_service import build_fit_analysis
from src.services.tailoring_service import build_tailored_resume_draft

from .fit_agent import FitAgent
from .job_agent import JobAgent
from .profile_agent import ProfileAgent
from .review_agent import ReviewAgent
from .strategy_agent import StrategyAgent
from .tailoring_agent import TailoringAgent


LOGGER = get_logger(__name__)


class ApplicationOrchestrator:
    def __init__(self, openai_service=None, allow_fallback=True, max_revision_passes=2):
        self._openai_service = openai_service or OpenAIService()
        self._allow_fallback = allow_fallback
        self._max_revision_passes = max(0, int(max_revision_passes))

    def run(
        self,
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis=None,
        tailored_draft=None,
    ) -> AgentWorkflowResult:
        if fit_analysis is None:
            fit_analysis = build_fit_analysis(candidate_profile, job_description)
        if tailored_draft is None:
            tailored_draft = build_tailored_resume_draft(
                candidate_profile,
                job_description,
                fit_analysis,
            )

        if self._openai_service.is_available():
            try:
                return self._run_pipeline(
                    candidate_profile,
                    job_description,
                    fit_analysis,
                    tailored_draft,
                    openai_service=self._openai_service,
                    mode="openai",
                    model_name=self._openai_service.model,
                    max_revision_passes=self._max_revision_passes,
                )
            except AgentExecutionError:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "orchestrator_openai_fallback",
                    "OpenAI orchestration failed; falling back to deterministic mode.",
                    model=self._openai_service.model,
                    max_revision_passes=self._max_revision_passes,
                )
                if not self._allow_fallback:
                    raise

        return self._run_pipeline(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            openai_service=None,
            mode="deterministic_fallback",
            model_name="fallback",
            max_revision_passes=self._max_revision_passes,
        )

    @staticmethod
    def _run_pipeline(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        openai_service,
        mode,
        model_name,
        max_revision_passes=2,
    ):
        tailoring_agent = TailoringAgent(openai_service)
        review_agent = ReviewAgent(openai_service)
        strategy_agent = StrategyAgent(openai_service)
        review_history = []

        tailoring_output = None
        strategy_output = None
        review_output = None

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

        profile_output = run_agent_step(
            "profile",
            lambda: ProfileAgent(openai_service).run(candidate_profile),
        )
        job_output = run_agent_step(
            "job",
            lambda: JobAgent(openai_service).run(job_description),
        )
        fit_output = run_agent_step(
            "fit",
            lambda: FitAgent(openai_service).run(
                candidate_profile,
                job_description,
                fit_analysis,
                profile_output,
                job_output,
            ),
        )

        for pass_index in range(1, max_revision_passes + 2):
            revision_requests = review_output.revision_requests if review_output else None
            previous_tailoring_output = tailoring_output
            tailoring_output = run_agent_step(
                "tailoring",
                lambda: tailoring_agent.run(
                    candidate_profile,
                    job_description,
                    fit_analysis,
                    tailored_draft,
                    profile_output,
                    fit_output,
                    previous_tailoring_output=previous_tailoring_output,
                    revision_requests=revision_requests,
                ),
                pass_index=pass_index,
                revision_request_count=len(revision_requests or []),
            )
            strategy_output = run_agent_step(
                "strategy",
                lambda: strategy_agent.run(
                    candidate_profile,
                    job_description,
                    fit_analysis,
                    profile_output,
                    fit_output,
                    tailoring_output,
                ),
                pass_index=pass_index,
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
                pass_index=pass_index,
            )
            review_history.append(
                ReviewPassResult(
                    pass_index=pass_index,
                    tailoring=tailoring_output,
                    strategy=strategy_output,
                    review=review_output,
                )
            )
            if review_output.approved:
                break

        log_event(
            LOGGER,
            logging.INFO,
            "orchestrator_completed",
            "Application orchestration completed.",
            mode=mode,
            model=model_name,
            review_passes=len(review_history),
            approved=review_output.approved if review_output else False,
        )

        return AgentWorkflowResult(
            mode=mode,
            model=model_name,
            profile=profile_output,
            job=job_output,
            fit=fit_output,
            tailoring=tailoring_output,
            strategy=strategy_output,
            review=review_output,
            review_history=review_history,
        )
