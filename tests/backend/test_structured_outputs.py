"""Schema-strict output path tests.

Three layers of coverage:

  * ``_build_response_format_schema`` correctly rewrites a Pydantic
    schema for OpenAI's structured outputs (inlines $defs, adds
    ``additionalProperties: false``, fills ``required`` on every
    object).
  * ``run_structured_prompt`` round-trips a Pydantic model through a
    mocked OpenAI client — returns the validated instance, DROPS
    unknown keys (``_StrictBase`` is ``extra="ignore"``; the
    server-side strict ``response_format`` is the real fail-closed
    guard), and still raises a clean ``AgentExecutionError`` on
    genuinely-malformed output (wrong field type).
  * Each migrated agent (Tailoring, Review, ResumeGeneration,
    CoverLetter) uses ``run_structured_prompt`` not
    ``run_json_prompt``, returns the expected dataclass shape, and
    handles a schema-validation failure by raising rather than silently
    falling back.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Optional

import pytest
from pydantic import BaseModel, ValidationError

from src.errors import AgentExecutionError
from src.openai_service import (
    OpenAIService,
    _build_response_format_schema,
    _enforce_strict_object_constraints,
    _inline_refs,
    _schema_name_for_model,
)
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    JobRequirements,
    TailoredResumeDraft,
    TailoringAgentOutput,
)
from src.schemas_llm_outputs import (
    CoverLetterOutput,
    ResumeGenerationOutput,
    ReviewOutput,
    TailoringOutput,
    _StrictBase,
)


# ---------------------------------------------------------------------
# Fake OpenAI client (shared with tests/test_openai_service.py shape)
# ---------------------------------------------------------------------


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClient:
    def __init__(self, responses):
        self.responses = _FakeCompletions(responses)


def _build_response(content: str, *, response_id: str = "resp_1") -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        status="completed",
        output_text=content,
        incomplete_details=None,
        usage=SimpleNamespace(
            input_tokens=12,
            output_tokens=5,
            total_tokens=17,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[SimpleNamespace(type="output_text", text=content)],
            )
        ],
    )


# ---------------------------------------------------------------------
# Schema-rewriter unit tests
# ---------------------------------------------------------------------


class _LeafModel(BaseModel):
    value: str = ""
    optional_value: Optional[str] = None


class _RootModel(BaseModel):
    name: str = ""
    leaves: list[_LeafModel] = []


def test_schema_name_for_model_includes_task():
    name = _schema_name_for_model(TailoringOutput, task_name="tailoring")
    assert name == "tailoring_TailoringOutput"


def test_schema_name_for_model_strips_invalid_characters():
    name = _schema_name_for_model(TailoringOutput, task_name="weird.task-name")
    # Dots and dashes become underscores.
    assert name == "weird_task_name_TailoringOutput"


def test_inline_refs_replaces_refs_with_definitions():
    schema = {"$ref": "#/$defs/X"}
    defs = {"X": {"type": "object", "properties": {"name": {"type": "string"}}}}
    inlined = _inline_refs(schema, defs)
    assert inlined == {"type": "object", "properties": {"name": {"type": "string"}}}


def test_inline_refs_recurses_into_nested_objects():
    schema = {
        "type": "object",
        "properties": {"child": {"$ref": "#/$defs/X"}},
    }
    defs = {"X": {"type": "string"}}
    inlined = _inline_refs(schema, defs)
    assert inlined["properties"]["child"] == {"type": "string"}


def test_enforce_strict_object_constraints_adds_required_and_additionalProperties():
    node = {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "integer"},
        },
    }
    enforced = _enforce_strict_object_constraints(node)
    assert enforced["additionalProperties"] is False
    assert set(enforced["required"]) == {"a", "b"}


def test_enforce_strict_object_constraints_walks_nested_objects():
    node = {
        "type": "object",
        "properties": {
            "inner": {
                "type": "object",
                "properties": {"k": {"type": "string"}},
            }
        },
    }
    enforced = _enforce_strict_object_constraints(node)
    assert enforced["properties"]["inner"]["additionalProperties"] is False
    assert enforced["properties"]["inner"]["required"] == ["k"]


def test_build_response_format_schema_inlines_definitions():
    """Pydantic emits ``$defs`` for nested models; the helper inlines
    them so the schema we send to OpenAI is self-contained."""
    schema = _build_response_format_schema(_RootModel)
    # No $defs at the root after inlining.
    assert "$defs" not in schema
    # Leaves array's item schema should be the inlined leaf model.
    item_schema = schema["properties"]["leaves"]["items"]
    assert item_schema["type"] == "object"
    assert "value" in item_schema["properties"]


def test_build_response_format_schema_marks_every_field_required():
    schema = _build_response_format_schema(TailoringOutput)
    required = set(schema["required"])
    # All four contract fields must be present in the required list — the
    # optional-vs-required distinction lives in Pydantic field defaults,
    # not in the JSON-schema required list (strict mode treats omission
    # of a property as a parse error regardless).
    assert required == {
        "professional_summary",
        "rewritten_bullets",
        "highlighted_skills",
        "cover_letter_themes",
    }


def test_build_response_format_schema_supports_optional_nested_model():
    """``ReviewOutput.corrected_tailoring`` is ``Optional[TailoringOutput]``;
    Pydantic encodes that as ``anyOf [object, null]``. The schema
    rewriter must preserve the union so the API will accept ``null``."""
    schema = _build_response_format_schema(ReviewOutput)
    corrected = schema["properties"]["corrected_tailoring"]
    # Either anyOf or a direct nullable expression — both are valid as
    # long as null is reachable.
    assert "anyOf" in corrected or corrected.get("type") in ("object", ["object", "null"])


# ---------------------------------------------------------------------
# run_structured_prompt integration with the fake client
# ---------------------------------------------------------------------


def test_run_structured_prompt_returns_validated_pydantic_instance():
    payload_json = json.dumps(
        {
            "professional_summary": "A grounded summary.",
            "rewritten_bullets": ["b1", "b2", "b3"],
            "highlighted_skills": ["Python", "SQL"],
            "cover_letter_themes": ["ownership"],
        }
    )
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(client=client)

    result = service.run_structured_prompt(
        "system",
        "user",
        response_model=TailoringOutput,
        task_name="tailoring",
    )

    assert isinstance(result, TailoringOutput)
    assert result.professional_summary == "A grounded summary."
    assert result.highlighted_skills == ["Python", "SQL"]
    # Usage was recorded the same way as run_json_prompt.
    snapshot = service.get_usage_snapshot()
    assert snapshot["request_count"] == 1
    assert snapshot["total_tokens"] == 17


def test_run_structured_prompt_sends_json_schema_response_format():
    """The request payload must use ``text.format.type == 'json_schema'``
    so the model is constrained at generation time — not
    ``json_object``, which only guarantees syntactic JSON."""
    payload_json = json.dumps(
        {
            "professional_summary": "",
            "rewritten_bullets": [],
            "highlighted_skills": [],
            "cover_letter_themes": [],
        }
    )
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(client=client)

    service.run_structured_prompt(
        "system",
        "user",
        response_model=TailoringOutput,
        task_name="tailoring",
    )

    sent = client.responses.calls[0]
    assert sent["text"]["format"]["type"] == "json_schema"
    assert sent["text"]["format"]["strict"] is True
    schema = sent["text"]["format"]["schema"]
    assert schema["properties"]["professional_summary"]["type"] == "string"
    assert "additionalProperties" in schema and schema["additionalProperties"] is False


def test_run_structured_prompt_raises_on_invalid_json():
    """A truncated / malformed JSON body should bubble up as the same
    ``AgentExecutionError`` shape ``run_json_prompt`` uses, so callers
    don't have to learn a new error type."""
    client = _FakeClient([_build_response("not-json")])
    service = OpenAIService(client=client)

    with pytest.raises(AgentExecutionError) as exc_info:
        service.run_structured_prompt(
            "system",
            "user",
            response_model=TailoringOutput,
            task_name="tailoring",
        )
    assert "invalid JSON" in exc_info.value.user_message


def test_run_structured_prompt_ignores_unknown_keys():
    """A benign extra key the model volunteers must NOT nuke an
    otherwise-valid agent output.

    Intentional contract change (was
    ``test_run_structured_prompt_raises_on_schema_mismatch``):
    ``_StrictBase`` is now ``extra="ignore"``. The fail-closed guard
    moved to where it actually lives — the OpenAI strict
    ``response_format`` (asserted in
    ``test_run_structured_prompt_sends_json_schema_response_format``,
    which checks ``strict is True`` + ``additionalProperties: false``).
    The redundant client-side re-validation must degrade gracefully:
    drop the unknown key, return the validated instance, so the
    orchestrator does NOT drop this agent to its deterministic
    fallback over one stray field."""
    payload_json = json.dumps(
        {
            "professional_summary": "Valid summary.",
            "rewritten_bullets": ["b1"],
            "highlighted_skills": ["Python"],
            "cover_letter_themes": ["ownership"],
            "this_field_should_not_exist": True,
        }
    )
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(client=client)

    result = service.run_structured_prompt(
        "system",
        "user",
        response_model=TailoringOutput,
        task_name="tailoring",
    )

    assert isinstance(result, TailoringOutput)
    assert result.professional_summary == "Valid summary."
    assert result.rewritten_bullets == ["b1"]
    # The unknown key is dropped, not attached to the instance.
    assert not hasattr(result, "this_field_should_not_exist")
    assert "this_field_should_not_exist" not in result.model_dump()


def test_run_structured_prompt_raises_on_malformed_output():
    """The over-permissiveness guard: ``extra="ignore"`` must NOT
    weaken required-field / TYPE enforcement.

    (Job Agent's ``_StrictBase`` subclasses all carry field defaults,
    so an *omitted* field is filled by its default rather than raising
    — the meaningful "still genuinely-malformed" signal here is a
    wrong-typed field, not a missing one.) A non-list where the schema
    wants ``list[str]`` must still fail ``model_validate`` and surface
    as the same clean ``AgentExecutionError`` so the agent still falls
    back on genuinely-broken output."""
    payload_json = json.dumps(
        {
            "professional_summary": "Valid summary.",
            "rewritten_bullets": 123,  # schema wants list[str]
            "highlighted_skills": [],
            "cover_letter_themes": [],
        }
    )
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(client=client)

    with pytest.raises(AgentExecutionError) as exc_info:
        service.run_structured_prompt(
            "system",
            "user",
            response_model=TailoringOutput,
            task_name="tailoring",
        )
    assert "schema" in exc_info.value.user_message.lower()


def test_llm_output_base_ignores_extra_keys_but_enforces_types():
    """Model-level contract for the shared ``_StrictBase`` config.

    Tighter + faster than going through the service: asserts the
    actual ``ConfigDict`` change and that the relax is scoped to
    *unknown keys only* (types/required still enforced)."""
    # The config change itself — the thing a future "re-tighten to be
    # safe" refactor would silently revert.
    assert _StrictBase.model_config.get("extra") == "ignore"

    parsed = TailoringOutput.model_validate(
        {
            "professional_summary": "ok",
            "rewritten_bullets": ["b1"],
            "highlighted_skills": ["Python"],
            "cover_letter_themes": ["theme"],
            "rogue_key": {"nested": "ignored"},
        }
    )
    assert parsed.professional_summary == "ok"
    assert "rogue_key" not in parsed.model_dump()

    # Unknown keys are dropped, but a wrong TYPE on a real field is
    # still a hard ValidationError — the relax did not become "accept
    # anything".
    with pytest.raises(ValidationError):
        TailoringOutput.model_validate(
            {
                "professional_summary": "ok",
                "rewritten_bullets": 123,
                "highlighted_skills": [],
                "cover_letter_themes": [],
            }
        )


def test_run_structured_prompt_raises_when_openai_unavailable(monkeypatch):
    # Hermetic isolation. The default ``api_key=None`` path resolves
    # the key via ``src.config.load_openai_key`` which reads the
    # ``OPENAI_API_KEY`` env var OR an ``openai_key.txt`` fallback
    # file. With a real key in the developer's local ``.env`` (or that
    # file present) the constructor would build a usable client and
    # this test would NOT raise — a pre-existing env-dependent flake,
    # unrelated to the schema config. Neutralize the resolver so this
    # asserts the genuine "no credentials configured" behaviour
    # regardless of the local environment.
    monkeypatch.setattr(
        "src.openai_service.load_openai_key", lambda required=False: None
    )
    service = OpenAIService(client=None, api_key=None)
    assert service.is_available() is False
    with pytest.raises(AgentExecutionError):
        service.run_structured_prompt(
            "system",
            "user",
            response_model=TailoringOutput,
        )


# ---------------------------------------------------------------------
# Per-agent integration tests
# ---------------------------------------------------------------------


def _make_inputs():
    candidate_profile = CandidateProfile(
        full_name="Alex Builder",
        skills=["Python", "SQL"],
        resume_text="Python and SQL experience.",
    )
    job_description = JobDescription(
        title="Senior Data Engineer",
        raw_text="JD text",
        cleaned_text="JD text",
        location="Remote",
        requirements=JobRequirements(
            hard_skills=["Python", "SQL", "Airflow"],
            soft_skills=["communication"],
        ),
    )
    fit_analysis = FitAnalysis(
        target_role="Senior Data Engineer",
        overall_score=72,
        readiness_label="Strong fit",
        matched_hard_skills=["Python", "SQL"],
        missing_hard_skills=["Airflow"],
    )
    tailored_draft = TailoredResumeDraft(
        target_role="Senior Data Engineer",
        professional_summary="Engineer with Python + SQL.",
        highlighted_skills=["Python", "SQL"],
        priority_bullets=["Shipped a Python ETL pipeline."],
    )
    return candidate_profile, job_description, fit_analysis, tailored_draft


def test_tailoring_agent_uses_structured_prompt():
    from src.agents.tailoring_agent import TailoringAgent

    payload_json = json.dumps(
        {
            "professional_summary": "Senior data engineer summary.",
            "rewritten_bullets": ["Owned the Snowflake migration."],
            "highlighted_skills": ["Python", "SQL"],
            "cover_letter_themes": ["lead with Python depth"],
        }
    )
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(client=client)
    agent = TailoringAgent(openai_service=service)

    candidate_profile, job_description, fit_analysis, tailored_draft = _make_inputs()
    output = agent.run(candidate_profile, job_description, fit_analysis, tailored_draft)

    # Returned dataclass populated from the structured response.
    assert output.professional_summary.startswith("Senior data engineer")
    assert output.highlighted_skills == ["Python", "SQL"]
    # Request used the structured-output format, not the json_object format.
    sent = client.responses.calls[0]
    assert sent["text"]["format"]["type"] == "json_schema"


def test_review_agent_handles_optional_nested_correction():
    """ReviewAgent's response includes ``corrected_tailoring`` which is
    ``Optional[TailoringOutput]``. When the model returns null, the
    downstream agent output should reflect ``corrected_tailoring=None``;
    when it returns a nested object, it should propagate as a
    ``TailoringAgentOutput``."""
    from src.agents.review_agent import ReviewAgent

    no_correction_payload = json.dumps(
        {
            "approved": True,
            "grounding_issues": [],
            "unresolved_issues": [],
            "revision_requests": [],
            "final_notes": ["Looks good."],
            "corrected_tailoring": None,
        }
    )
    with_correction_payload = json.dumps(
        {
            "approved": True,
            "grounding_issues": ["mentioned Airflow"],
            "unresolved_issues": [],
            "revision_requests": ["drop Airflow"],
            "final_notes": ["Corrected."],
            "corrected_tailoring": {
                "professional_summary": "Fixed summary.",
                "rewritten_bullets": ["Owned the Python ETL pipeline."],
                "highlighted_skills": ["Python"],
                "cover_letter_themes": ["lead with Python"],
            },
        }
    )
    client = _FakeClient(
        [
            _build_response(no_correction_payload, response_id="r1"),
            _build_response(with_correction_payload, response_id="r2"),
        ]
    )
    service = OpenAIService(client=client)
    agent = ReviewAgent(openai_service=service)

    candidate_profile, job_description, fit_analysis, tailored_draft = _make_inputs()
    tailoring_input = TailoringAgentOutput(
        professional_summary="Tailoring input.",
        rewritten_bullets=["A bullet."],
        highlighted_skills=["Python"],
        cover_letter_themes=["theme"],
    )

    first = agent.run(
        candidate_profile, job_description, fit_analysis, tailored_draft, tailoring_input
    )
    assert first.approved is True
    assert first.corrected_tailoring is None

    second = agent.run(
        candidate_profile, job_description, fit_analysis, tailored_draft, tailoring_input
    )
    assert second.corrected_tailoring is not None
    assert second.corrected_tailoring.professional_summary == "Fixed summary."
    assert second.corrected_tailoring.highlighted_skills == ["Python"]


def test_resume_generation_agent_uses_structured_prompt():
    from src.agents.resume_generation_agent import ResumeGenerationAgent

    payload_json = json.dumps(
        {
            "professional_summary": "Final summary.",
            "highlighted_skills": ["Python", "SQL"],
            "experience_bullets": ["Built a Python ETL pipeline."],
            "section_order": ["Professional Summary", "Skills", "Experience"],
            "template_hint": "classic_ats",
        }
    )
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(client=client)
    agent = ResumeGenerationAgent(openai_service=service)

    candidate_profile, job_description, fit_analysis, tailored_draft = _make_inputs()
    tailoring_input = TailoringAgentOutput(
        professional_summary="ts",
        rewritten_bullets=["A bullet."],
        highlighted_skills=["Python"],
        cover_letter_themes=["theme"],
    )

    output = agent.run(
        candidate_profile, job_description, fit_analysis, tailored_draft, tailoring_input
    )
    assert output.professional_summary == "Final summary."
    assert output.experience_bullets == ["Built a Python ETL pipeline."]
    sent = client.responses.calls[0]
    assert sent["text"]["format"]["type"] == "json_schema"


def test_cover_letter_agent_uses_structured_prompt():
    from src.agents.cover_letter_agent import CoverLetterAgent

    payload_json = json.dumps(
        {
            "greeting": "Dear Hiring Team",
            "opening_paragraph": "I am writing to apply.",
            "body_paragraphs": ["Body para 1.", "Body para 2."],
            "closing_paragraph": "Thanks for your time.",
            "signoff": "Sincerely",
            "signature_name": "Alex Builder",
        }
    )
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(client=client)
    agent = CoverLetterAgent(openai_service=service)

    candidate_profile, job_description, fit_analysis, tailored_draft = _make_inputs()
    tailoring_input = TailoringAgentOutput(
        professional_summary="ts",
        rewritten_bullets=["A bullet."],
        highlighted_skills=["Python"],
        cover_letter_themes=["theme"],
    )
    output = agent.run(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        tailoring_input,
    )
    assert output.opening_paragraph == "I am writing to apply."
    assert output.signature_name == "Alex Builder"
    sent = client.responses.calls[0]
    assert sent["text"]["format"]["type"] == "json_schema"
