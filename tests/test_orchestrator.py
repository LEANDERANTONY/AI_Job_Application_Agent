from src.agents.orchestrator import ApplicationOrchestrator
from src.errors import AgentExecutionError
from src.schemas import ResumeDocument
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume


def _build_candidate_profile():
    return build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker communication\n"
                "Built machine learning pipelines and production applications."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )


def _build_job_description():
    return build_job_description_from_text(
        "Machine Learning Engineer\n"
        "Location: Chennai, India\n"
        "Required: Python, SQL, Docker, AWS, communication.\n"
        "Need 3+ years of experience.\n"
    )


class FakeUnavailableOpenAIService:
    model = "fake-model"

    @staticmethod
    def is_available():
        return False


class FakeOpenAIService:
    def __init__(self):
        self.model = "fake-model"
        self._responses = [
            {
                "positioning_headline": "Applied AI engineer with grounded product delivery evidence",
                "evidence_highlights": ["Python", "Docker", "Production applications"],
                "strengths": ["Hands-on Python delivery", "Usable resume evidence"],
                "cautions": ["AWS is not evidenced directly"],
            },
            {
                "requirement_summary": "Production ML role with strong implementation expectations.",
                "priority_skills": ["Python", "SQL", "Docker", "AWS"],
                "must_have_themes": ["Production ML systems", "Communication"],
                "messaging_guidance": ["Mirror delivery language from the JD."],
            },
            {
                "fit_summary": "Strong fit overall with one visible cloud gap.",
                "top_matches": ["Python", "SQL", "Docker"],
                "key_gaps": ["AWS"],
                "interview_themes": ["Production delivery", "Cross-team communication"],
            },
            {
                "professional_summary": "Grounded summary for the role.",
                "rewritten_bullets": ["Built production applications using Python and Docker."],
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "cover_letter_themes": ["Strong implementation fit."],
            },
            {
                "recruiter_positioning": "Position the candidate as a grounded implementation-focused ML engineer.",
                "cover_letter_talking_points": ["Lead with production application delivery evidence."],
                "interview_preparation_themes": ["Production delivery", "Cross-team communication"],
                "portfolio_project_emphasis": ["Highlight productized ML work using Python and Docker."],
            },
            {
                "approved": True,
                "grounding_issues": [],
                "revision_requests": [],
                "final_notes": ["Grounded output."],
            },
            {
                "professional_summary": "Final tailored summary for the generated resume.",
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "experience_bullets": ["Built production applications using Python and Docker."],
                "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
                "template_hint": "classic_ats",
            },
        ]

    @staticmethod
    def is_available():
        return True

    def run_json_prompt(self, system_prompt, user_prompt, expected_keys=None, **kwargs):
        return self._responses.pop(0)


class FailingOpenAIService:
    model = "failing-model"

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def run_json_prompt(system_prompt, user_prompt, expected_keys=None, **kwargs):
        raise AgentExecutionError("boom")


class FakeRevisionLoopOpenAIService:
    def __init__(self):
        self.model = "fake-model"
        self._responses = [
            {
                "positioning_headline": "Applied AI engineer with grounded product delivery evidence",
                "evidence_highlights": ["Python", "Docker", "Production applications"],
                "strengths": ["Hands-on Python delivery", "Usable resume evidence"],
                "cautions": ["AWS is not evidenced directly"],
            },
            {
                "requirement_summary": "Production ML role with strong implementation expectations.",
                "priority_skills": ["Python", "SQL", "Docker", "AWS"],
                "must_have_themes": ["Production ML systems", "Communication"],
                "messaging_guidance": ["Mirror delivery language from the JD."],
            },
            {
                "fit_summary": "Strong fit overall with one visible cloud gap.",
                "top_matches": ["Python", "SQL", "Docker"],
                "key_gaps": ["AWS"],
                "interview_themes": ["Production delivery", "Cross-team communication"],
            },
            {
                "professional_summary": "Initial summary with unsupported AWS emphasis.",
                "rewritten_bullets": ["Led AWS-native production deployments for ML services."],
                "highlighted_skills": ["Python", "SQL", "AWS"],
                "cover_letter_themes": ["Strong cloud fit."],
            },
            {
                "recruiter_positioning": "Initial recruiter positioning with unsupported AWS depth.",
                "cover_letter_talking_points": ["Emphasize AWS-native production ownership."],
                "interview_preparation_themes": ["Cloud architecture leadership"],
                "portfolio_project_emphasis": ["Feature AWS-heavy production work."],
            },
            {
                "approved": False,
                "grounding_issues": ["AWS claim is stronger than the source profile supports."],
                "revision_requests": ["Remove unsupported AWS delivery claims and keep the summary grounded."],
                "final_notes": ["Needs a more conservative rewrite."],
            },
            {
                "professional_summary": "Revised grounded summary for the role.",
                "rewritten_bullets": ["Built production applications using Python and Docker."],
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "cover_letter_themes": ["Strong implementation fit."],
            },
            {
                "recruiter_positioning": "Revised grounded implementation-focused positioning.",
                "cover_letter_talking_points": ["Lead with delivery evidence in Python and Docker."],
                "interview_preparation_themes": ["Production delivery", "Grounded communication"],
                "portfolio_project_emphasis": ["Highlight production applications that show end-to-end delivery."],
            },
            {
                "approved": True,
                "grounding_issues": [],
                "revision_requests": [],
                "final_notes": ["Grounded after revision."],
            },
            {
                "professional_summary": "Resume-ready grounded summary for the role.",
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "experience_bullets": ["Built production applications using Python and Docker."],
                "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
                "template_hint": "classic_ats",
            },
        ]

    @staticmethod
    def is_available():
        return True

    def run_json_prompt(self, system_prompt, user_prompt, expected_keys=None, **kwargs):
        return self._responses.pop(0)


class FakeNeverApprovedOpenAIService:
    def __init__(self):
        self.model = "fake-model"
        self._responses = [
            {
                "positioning_headline": "Applied AI engineer with grounded product delivery evidence",
                "evidence_highlights": ["Python", "Docker", "Production applications"],
                "strengths": ["Hands-on Python delivery", "Usable resume evidence"],
                "cautions": ["AWS is not evidenced directly"],
            },
            {
                "requirement_summary": "Production ML role with strong implementation expectations.",
                "priority_skills": ["Python", "SQL", "Docker", "AWS"],
                "must_have_themes": ["Production ML systems", "Communication"],
                "messaging_guidance": ["Mirror delivery language from the JD."],
            },
            {
                "fit_summary": "Strong fit overall with one visible cloud gap.",
                "top_matches": ["Python", "SQL", "Docker"],
                "key_gaps": ["AWS"],
                "interview_themes": ["Production delivery", "Cross-team communication"],
            },
            {
                "professional_summary": "First pass summary.",
                "rewritten_bullets": ["First pass bullet."],
                "highlighted_skills": ["Python", "AWS"],
                "cover_letter_themes": ["First pass theme."],
            },
            {
                "recruiter_positioning": "First pass positioning.",
                "cover_letter_talking_points": ["First pass talking point."],
                "interview_preparation_themes": ["First pass interview theme."],
                "portfolio_project_emphasis": ["First pass portfolio emphasis."],
            },
            {
                "approved": False,
                "grounding_issues": ["Unsupported claim remains."],
                "revision_requests": ["Remove unsupported claim."],
                "final_notes": ["Needs revision."],
            },
            {
                "professional_summary": "Second pass summary.",
                "rewritten_bullets": ["Second pass bullet."],
                "highlighted_skills": ["Python"],
                "cover_letter_themes": ["Second pass theme."],
            },
            {
                "recruiter_positioning": "Second pass positioning.",
                "cover_letter_talking_points": ["Second pass talking point."],
                "interview_preparation_themes": ["Second pass interview theme."],
                "portfolio_project_emphasis": ["Second pass portfolio emphasis."],
            },
            {
                "approved": False,
                "grounding_issues": ["Unsupported claim remains."],
                "revision_requests": ["Remove unsupported claim."],
                "final_notes": ["Still needs revision."],
            },
            {
                "professional_summary": "Second pass final resume summary.",
                "highlighted_skills": ["Python"],
                "experience_bullets": ["Second pass bullet."],
                "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
                "template_hint": "classic_ats",
            },
        ]

    @staticmethod
    def is_available():
        return True

    def run_json_prompt(self, system_prompt, user_prompt, expected_keys=None, **kwargs):
        return self._responses.pop(0)


class SpyStrategyRevisionOpenAIService(FakeRevisionLoopOpenAIService):
    def __init__(self):
        super().__init__()
        self.strategy_prompts = []

    def run_json_prompt(self, system_prompt, user_prompt, expected_keys=None, **kwargs):
        if kwargs.get("task_name") == "strategy":
            self.strategy_prompts.append(user_prompt)
        return super().run_json_prompt(system_prompt, user_prompt, expected_keys=expected_keys, **kwargs)


def test_orchestrator_runs_in_deterministic_fallback_mode():
    orchestrator = ApplicationOrchestrator(openai_service=FakeUnavailableOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "deterministic_fallback"
    assert result.model == "fallback"
    assert result.attempted_assisted is False
    assert result.profile.positioning_headline
    assert result.fit.fit_summary
    assert result.tailoring.professional_summary


def test_orchestrator_uses_openai_service_when_available():
    orchestrator = ApplicationOrchestrator(openai_service=FakeOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert result.model == "fake-model"
    assert result.profile.positioning_headline == (
        "Applied AI engineer with grounded product delivery evidence"
    )
    assert result.review.approved is True
    assert result.tailoring.rewritten_bullets == [
        "Built production applications using Python and Docker."
    ]
    assert result.strategy.recruiter_positioning == (
        "Position the candidate as a grounded implementation-focused ML engineer."
    )
    assert result.resume_generation.professional_summary == "Final tailored summary for the generated resume."
    assert len(result.review_history) == 1
    assert result.review_history[0].pass_index == 1


def test_orchestrator_falls_back_if_ai_execution_fails():
    orchestrator = ApplicationOrchestrator(openai_service=FailingOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "deterministic_fallback"
    assert result.model == "fallback"
    assert result.attempted_assisted is True
    assert result.fallback_reason == "boom"
    assert result.review.final_notes


def test_orchestrator_retries_tailoring_when_review_rejects():
    orchestrator = ApplicationOrchestrator(openai_service=FakeRevisionLoopOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert result.review.approved is True
    assert result.tailoring.professional_summary == "Revised grounded summary for the role."
    assert result.strategy.recruiter_positioning == "Revised grounded implementation-focused positioning."
    assert result.resume_generation.professional_summary == "Resume-ready grounded summary for the role."
    assert len(result.review_history) == 2
    assert result.review_history[0].review.approved is False
    assert result.review_history[1].review.approved is True


def test_orchestrator_stops_after_max_revision_passes():
    orchestrator = ApplicationOrchestrator(
        openai_service=FakeNeverApprovedOpenAIService(),
        max_revision_passes=1,
    )

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert result.review.approved is False
    assert result.tailoring.professional_summary == "Second pass summary."
    assert result.strategy.recruiter_positioning == "Second pass positioning."
    assert result.resume_generation.professional_summary == "Second pass final resume summary."
    assert len(result.review_history) == 2
    assert result.review_history[-1].pass_index == 2


def test_orchestrator_reports_progress_updates():
    orchestrator = ApplicationOrchestrator(openai_service=FakeRevisionLoopOpenAIService())
    updates = []

    result = orchestrator.run(
        _build_candidate_profile(),
        _build_job_description(),
        progress_callback=lambda title, detail, value: updates.append((title, detail, value)),
    )

    assert result.mode == "openai"
    assert updates[0] == (
        "Workflow crew",
        "Opening your application brief and assigning the first agent.",
        3,
    )
    assert any(
        title == "Scout agent"
        and detail == "Pulling out the strongest grounded proof points from your resume."
        for title, detail, _ in updates
    )
    assert any(
        title == "Gatekeeper agent"
        and detail == "Reviewing pass 1; only the strongest work gets through."
        for title, detail, _ in updates
    )
    assert any(
        title == "Gatekeeper agent"
        and detail == "Sent it back for one more polish pass before approval."
        for title, detail, _ in updates
    )
    assert any(
        title == "Builder agent"
        and detail == "Packaging the final tailored resume and lining up the finish."
        for title, detail, _ in updates
    )
    assert updates[-1] == (
        "Workflow crew",
        "All agents are done. Finalizing your application outputs.",
        100,
    )


def test_orchestrator_passes_review_requests_to_strategy_retry():
    service = SpyStrategyRevisionOpenAIService()
    orchestrator = ApplicationOrchestrator(openai_service=service)

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert len(service.strategy_prompts) == 2
    assert "Revision Requests" in service.strategy_prompts[1]
    assert "Remove unsupported AWS delivery claims and keep the summary grounded." in service.strategy_prompts[1]
