from src.agents.orchestrator import ApplicationOrchestrator
from src.errors import AgentExecutionError
from src.schemas import ResumeDocument
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume


def _materialize_structured(response, response_model):
    """Helper for the fake services below.

    The legacy ``run_json_prompt`` fakes returned raw dicts. After the
    schema-strict migration the agents call ``run_structured_prompt``
    and expect a validated Pydantic instance. We keep the queued
    response shape as dicts (cleaner to read in the test setup) and
    materialize the expected model here so tests don't have to be
    rewritten as Pydantic constructors.
    """
    if isinstance(response, BaseException):
        raise response
    return response_model.model_validate(response)


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
                "professional_summary": "Grounded summary for the role.",
                "rewritten_bullets": ["Built production applications using Python and Docker."],
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "cover_letter_themes": ["Strong implementation fit."],
            },
            {
                "approved": True,
                "grounding_issues": [],
                "unresolved_issues": [],
                "revision_requests": [],
                "final_notes": ["Grounded output."],
                "corrected_tailoring": {
                    "professional_summary": "Grounded summary for the role.",
                    "rewritten_bullets": ["Built production applications using Python and Docker."],
                    "highlighted_skills": ["Python", "SQL", "Docker"],
                    "cover_letter_themes": ["Strong implementation fit."],
                },
            },
            {
                "professional_summary": "Final tailored summary for the generated resume.",
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "experience_bullets": ["Built production applications using Python and Docker."],
                "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
                "template_hint": "classic_ats",
            },
            {
                "greeting": "Dear Hiring Team",
                "opening_paragraph": "I am excited to apply for the Machine Learning Engineer role and bring grounded implementation experience.",
                "body_paragraphs": [
                    "Strong implementation fit.",
                    "Built production applications using Python and Docker.",
                ],
                "closing_paragraph": "I would welcome the opportunity to discuss how my experience can support your team.",
                "signoff": "Sincerely",
                "signature_name": "Leander Antony",
            },
        ]

    @staticmethod
    def is_available():
        return True

    def run_json_prompt(self, system_prompt, user_prompt, expected_keys=None, **kwargs):
        return self._responses.pop(0)

    def run_structured_prompt(self, system_prompt, user_prompt, *, response_model, **kwargs):
        return _materialize_structured(self._responses.pop(0), response_model)


class FailingOpenAIService:
    model = "failing-model"

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def run_json_prompt(system_prompt, user_prompt, expected_keys=None, **kwargs):
        raise AgentExecutionError("boom")

    @staticmethod
    def run_structured_prompt(system_prompt, user_prompt, *, response_model, **kwargs):
        raise AgentExecutionError("boom")


class FakeCorrectionOpenAIService(FakeOpenAIService):
    def __init__(self):
        self.model = "fake-model"
        self._responses = [
            {
                "professional_summary": "Initial summary with unsupported AWS emphasis.",
                "rewritten_bullets": ["Led AWS-native production deployments for ML services."],
                "highlighted_skills": ["Python", "SQL", "AWS"],
                "cover_letter_themes": ["Strong cloud fit."],
            },
            {
                "approved": False,
                "grounding_issues": ["AWS claim is stronger than the source profile supports."],
                "unresolved_issues": [],
                "revision_requests": ["Remove unsupported AWS delivery claims and keep the summary grounded."],
                "final_notes": ["Grounded after direct review corrections."],
                "corrected_tailoring": {
                    "professional_summary": "Revised grounded summary for the role.",
                    "rewritten_bullets": ["Built production applications using Python and Docker."],
                    "highlighted_skills": ["Python", "SQL", "Docker"],
                    "cover_letter_themes": ["Lead with delivery evidence in Python and Docker."],
                },
            },
            {
                "professional_summary": "Resume-ready grounded summary for the role.",
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "experience_bullets": ["Built production applications using Python and Docker."],
                "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
                "template_hint": "classic_ats",
            },
            {
                "greeting": "Dear Hiring Team",
                "opening_paragraph": "I am excited to apply for the Machine Learning Engineer role and bring grounded implementation experience.",
                "body_paragraphs": [
                    "Lead with delivery evidence in Python and Docker.",
                    "Highlight production applications that show end-to-end delivery.",
                ],
                "closing_paragraph": "I would welcome the opportunity to discuss how my experience can support your team.",
                "signoff": "Sincerely",
                "signature_name": "Leander Antony",
            },
        ]


def test_orchestrator_runs_in_deterministic_fallback_mode():
    orchestrator = ApplicationOrchestrator(openai_service=FakeUnavailableOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "deterministic_fallback"
    assert result.model == "fallback"
    assert result.attempted_assisted is False
    assert result.tailoring.professional_summary
    assert result.review_history == []


def test_orchestrator_uses_openai_service_when_available():
    orchestrator = ApplicationOrchestrator(openai_service=FakeOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert result.model == "fake-model"
    assert result.profile.positioning_headline == ""
    assert result.job.requirement_summary == ""
    assert result.review.approved is True
    assert result.tailoring.rewritten_bullets == [
        "Built production applications using Python and Docker."
    ]
    assert result.strategy is None
    assert result.resume_generation.professional_summary == "Final tailored summary for the generated resume."
    assert result.cover_letter.opening_paragraph == "I am excited to apply for the Machine Learning Engineer role and bring grounded implementation experience."
    assert result.review_history == []


class FlakyOpenAIService:
    """Test double that returns a queue of responses or exceptions.

    Each call to ``run_json_prompt`` pops the next item: if it's an
    Exception, raise it; otherwise return it as the JSON payload.
    Lets us test the per-agent retry by interleaving exceptions with
    success responses.
    """

    def __init__(self, queue):
        self.model = "flaky-model"
        self._queue = list(queue)
        self.call_count = 0

    def is_available(self):
        return True

    def run_json_prompt(self, system_prompt, user_prompt, expected_keys=None, **kwargs):
        self.call_count += 1
        if not self._queue:
            raise AssertionError(
                "FlakyOpenAIService ran out of queued responses at call "
                f"#{self.call_count}"
            )
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def run_structured_prompt(self, system_prompt, user_prompt, *, response_model, **kwargs):
        self.call_count += 1
        if not self._queue:
            raise AssertionError(
                "FlakyOpenAIService ran out of queued responses at call "
                f"#{self.call_count}"
            )
        return _materialize_structured(self._queue.pop(0), response_model)


def _tailoring_response():
    return {
        "professional_summary": "Grounded summary for the role.",
        "rewritten_bullets": ["Built production applications using Python and Docker."],
        "highlighted_skills": ["Python", "SQL", "Docker"],
        "cover_letter_themes": ["Strong implementation fit."],
    }


def _review_response():
    return {
        "approved": True,
        "grounding_issues": [],
        "unresolved_issues": [],
        "revision_requests": [],
        "final_notes": ["Grounded output."],
        "corrected_tailoring": {
            "professional_summary": "Grounded summary for the role.",
            "rewritten_bullets": ["Built production applications using Python and Docker."],
            "highlighted_skills": ["Python", "SQL", "Docker"],
            "cover_letter_themes": ["Strong implementation fit."],
        },
    }


def _resume_generation_response():
    return {
        "professional_summary": "Final tailored summary for the generated resume.",
        "highlighted_skills": ["Python", "SQL", "Docker"],
        "experience_bullets": ["Built production applications using Python and Docker."],
        "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
        "template_hint": "classic_ats",
    }


def _cover_letter_response():
    return {
        "greeting": "Dear Hiring Team",
        "opening_paragraph": "I am excited to apply for the Machine Learning Engineer role and bring grounded implementation experience.",
        "body_paragraphs": [
            "Strong implementation fit.",
            "Built production applications using Python and Docker.",
        ],
        "closing_paragraph": "I would welcome the opportunity to discuss how my experience can support your team.",
        "signoff": "Sincerely",
        "signature_name": "Leander Antony",
    }


def test_orchestrator_retries_failing_agent_and_recovers():
    """If a single agent's LLM call raises AgentExecutionError on its
    first attempt, the orchestrator's per-agent retry should give it
    one more shot. If that succeeds, the whole pipeline still runs in
    `mode="openai"` — we should NOT degrade to deterministic just
    because of one transient failure mid-run."""
    # Tailoring agent fails on attempt 1 then succeeds on attempt 2.
    # Review, resume gen, cover letter all succeed first try.
    queue = [
        AgentExecutionError("transient — pretend the network blipped"),
        _tailoring_response(),         # tailoring succeeds on retry
        _review_response(),
        _resume_generation_response(),
        _cover_letter_response(),
    ]
    flaky = FlakyOpenAIService(queue)
    orchestrator = ApplicationOrchestrator(openai_service=flaky)

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai", (
        "Pipeline should stay in assisted mode after a recoverable agent retry."
    )
    assert result.model == "flaky-model"
    # 5 calls total: 2 for tailoring (one failed + one retry), then 1
    # each for review / resume gen / cover letter.
    assert flaky.call_count == 5
    # All four agents produced their assisted outputs.
    assert result.tailoring.rewritten_bullets == [
        "Built production applications using Python and Docker."
    ]
    assert result.review.approved is True
    assert result.resume_generation.professional_summary == \
        "Final tailored summary for the generated resume."
    assert result.cover_letter.opening_paragraph.startswith("I am excited to apply")


def test_orchestrator_per_agent_fallback_isolates_a_failing_agent():
    """When one agent's LLM attempts both fail (original + retry),
    that agent's deterministic fallback runs for THAT agent only —
    downstream agents still try the LLM path. Previously, one
    failing agent cascaded to "downgrade the whole run to
    deterministic" even though the rest would have succeeded."""
    # Tailoring fails twice (2 LLM calls burned), then per-agent
    # fallback kicks in for Tailoring. Review / ResumeGen / Cover
    # Letter all succeed first try (3 more LLM calls). Total: 5.
    queue = [
        AgentExecutionError("first tailoring failure"),
        AgentExecutionError("retry tailoring also failed"),
        _review_response(),
        _resume_generation_response(),
        _cover_letter_response(),
    ]
    flaky = FlakyOpenAIService(queue)
    orchestrator = ApplicationOrchestrator(openai_service=flaky)

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    # Pipeline as a whole stays in assisted mode — the LLM ran
    # successfully for 3 of the 4 agents.
    assert result.mode == "openai", (
        "Pipeline should remain assisted when only one agent fell back per-agent."
    )
    assert result.attempted_assisted is True
    # Exactly 5 LLM attempts: 2 failed tailoring + 3 successful
    # downstream agents (review / resume gen / cover letter).
    # NOT 2 (the old whole-pipeline-fallback behavior).
    assert flaky.call_count == 5
    # Tailoring output came from the deterministic fallback path
    # (TailoringAgent(None)._fallback), but the downstream LLM
    # outputs still populate.
    assert result.tailoring is not None
    assert result.review.approved is True
    assert result.resume_generation.professional_summary == \
        "Final tailored summary for the generated resume."
    assert result.cover_letter.opening_paragraph.startswith("I am excited to apply")


def test_orchestrator_marks_mode_deterministic_when_every_agent_fell_back():
    """If EVERY agent's LLM attempts fail and they all fall back to
    deterministic per-agent, the pipeline still completes (no
    cascade to whole-pipeline fallback) — but the result.mode
    should honestly reflect that no agent actually used the LLM.

    Auto-downgrade: result.mode flips from "openai" to
    "deterministic_fallback" when llm_success_count == 0.
    """
    # Every LLM call raises. With per-agent fallback, each agent's
    # deterministic path runs successfully → 4 agents complete with
    # zero LLM successes.
    queue = [AgentExecutionError(f"failure {i}") for i in range(20)]
    flaky = FlakyOpenAIService(queue)
    orchestrator = ApplicationOrchestrator(openai_service=flaky)

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    # Pipeline completed but no agent succeeded with LLM, so mode
    # must reflect that.
    assert result.mode == "deterministic_fallback"
    assert result.attempted_assisted is True


def test_orchestrator_falls_back_if_ai_execution_fails():
    orchestrator = ApplicationOrchestrator(openai_service=FailingOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "deterministic_fallback"
    assert result.model == "fallback"
    assert result.attempted_assisted is True
    assert result.fallback_reason == "boom"
    assert result.review.final_notes


def test_orchestrator_applies_review_corrections_without_second_pass():
    orchestrator = ApplicationOrchestrator(openai_service=FakeCorrectionOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert result.review.approved is True
    assert result.review.grounding_issues == ["AWS claim is stronger than the source profile supports."]
    assert result.review.unresolved_issues == []
    assert result.tailoring.professional_summary == "Revised grounded summary for the role."
    assert result.strategy is None
    assert result.review.corrected_tailoring is not None
    assert result.review.corrected_strategy is None
    assert result.resume_generation.professional_summary == "Resume-ready grounded summary for the role."
    assert result.cover_letter is not None
    assert result.cover_letter.body_paragraphs[0] == "Lead with delivery evidence in Python and Docker."
    assert result.review_history == []


def test_orchestrator_reports_progress_updates_for_single_pass_flow():
    orchestrator = ApplicationOrchestrator(openai_service=FakeCorrectionOpenAIService())
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
        title == "Matchmaker agent"
        and detail == "Comparing both sides, scoring overlap, and flagging the real gaps."
        for title, detail, _ in updates
    )
    assert any(
        title == "Gatekeeper agent"
        and detail == "Reviewing the drafted outputs and applying grounded corrections."
        for title, detail, _ in updates
    )
    assert any(
        title == "Cover letter agent"
        and detail == "Turning the approved story into a role-specific cover letter that is ready to send."
        for title, detail, _ in updates
    )
    assert not any(title == "Navigator agent" for title, _, _ in updates)
    assert not any("Sent it back" in detail for _, detail, _ in updates)
    assert updates[-1] == (
        "Workflow crew",
        "All agents are done. Finalizing your application outputs.",
        100,
    )
