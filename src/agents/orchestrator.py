from src.errors import AgentExecutionError
from src.openai_service import OpenAIService
from src.schemas import AgentWorkflowResult, CandidateProfile, JobDescription
from src.services.fit_service import build_fit_analysis
from src.services.tailoring_service import build_tailored_resume_draft

from .fit_agent import FitAgent
from .job_agent import JobAgent
from .profile_agent import ProfileAgent
from .review_agent import ReviewAgent
from .tailoring_agent import TailoringAgent


class ApplicationOrchestrator:
    def __init__(self, openai_service=None, allow_fallback=True):
        self._openai_service = openai_service or OpenAIService()
        self._allow_fallback = allow_fallback

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
                )
            except AgentExecutionError:
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
    ):
        profile_output = ProfileAgent(openai_service).run(candidate_profile)
        job_output = JobAgent(openai_service).run(job_description)
        fit_output = FitAgent(openai_service).run(
            candidate_profile,
            job_description,
            fit_analysis,
            profile_output,
            job_output,
        )
        tailoring_output = TailoringAgent(openai_service).run(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            profile_output,
            fit_output,
        )
        review_output = ReviewAgent(openai_service).run(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            tailoring_output,
        )

        return AgentWorkflowResult(
            mode=mode,
            model=model_name,
            profile=profile_output,
            job=job_output,
            fit=fit_output,
            tailoring=tailoring_output,
            review=review_output,
        )
