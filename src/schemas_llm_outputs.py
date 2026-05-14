"""Pydantic output models for the LLM agents and parsers.

The dataclass schemas in ``src/schemas.py`` describe the in-memory
post-processed shape — those types are forgiving on input
(``coerce_string_list`` clips lists, drops blanks, etc.) because
they're built from a JSON payload AFTER the LLM has emitted one.

This module is the OTHER direction: the schemas we hand to the
OpenAI Responses API as a ``response_format`` so the model can't
emit anything that doesn't validate. Each agent / parser gets one
top-level model whose field order, types, and required-vs-optional
markings mirror the contract dicts in ``src/prompts.py``.

Field rationale per model:

- We use ``str`` and ``list[str]`` everywhere a primitive is enough so
  the schema stays JSON-schema-friendly (OpenAI's structured outputs
  validate against draft-2020-12 with ``additionalProperties=false``
  enforcement).
- Lists are NOT length-constrained in the schema — the prompt still
  describes the soft target (e.g. "3-5 bullets"), but the post-processing
  helpers in ``src/agents/common.py`` clip lengths uniformly. Putting
  ``minItems``/``maxItems`` into the schema would force regeneration on
  legitimate edge cases (a candidate with two real bullets vs. three).
- Nested optional outputs (``ReviewOutput.corrected_tailoring``) use
  ``Optional[...] = None`` — the model is allowed to omit a fix when
  no correction is needed, matching the prompt's "return null" guidance.

Adding a new agent: define a model here, add a ``run_structured_prompt``
call site in the agent, and write a test under
``tests/backend/test_structured_outputs.py`` confirming the schema
binding round-trips through ``OpenAIService``.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------
# Shared base config
# ---------------------------------------------------------------------


class _StrictBase(BaseModel):
    """Common config for every LLM output model.

    ``extra='forbid'`` makes Pydantic reject any field the LLM tries to
    sneak in beyond the contract — useful both as a defensive net and
    as a signal that the prompt contract drifted from the schema.
    """

    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------
# Workflow agents (the four high-trust agents the orchestrator runs)
# ---------------------------------------------------------------------


class TailoringOutput(_StrictBase):
    """Schema for the TailoringAgent.

    Mirrors ``build_tailoring_agent_prompt``'s contract — same key
    names, same semantics. The agent post-processes lists via
    ``coerce_string_list(limit=...)``, so we don't bake length limits
    into the schema.
    """

    professional_summary: str = Field(
        default="",
        description="3-4 sentence tailored summary using only grounded claims",
    )
    rewritten_bullets: list[str] = Field(
        default_factory=list,
        description="3-5 tailored bullet ideas",
    )
    highlighted_skills: list[str] = Field(
        default_factory=list,
        description="4-8 skills to foreground",
    )
    cover_letter_themes: list[str] = Field(
        default_factory=list,
        description="2-4 cover-letter talking points",
    )


class ReviewOutput(_StrictBase):
    """Schema for the ReviewAgent.

    ``corrected_tailoring`` is the structurally interesting field —
    it's an optional nested ``TailoringOutput``. The prompt instructs
    the model to return ``null`` when no correction is needed; the
    JSON schema we generate from this model accepts both shapes via
    the ``Optional[...]`` union.
    """

    approved: bool = Field(
        default=True,
        description="True when the final outputs are safe to use after applying any corrections",
    )
    grounding_issues: list[str] = Field(
        default_factory=list,
        description="0-4 unsupported or weakly supported claims found before corrections",
    )
    unresolved_issues: list[str] = Field(
        default_factory=list,
        description="0-4 issues that still remain after corrections; empty when safe",
    )
    revision_requests: list[str] = Field(
        default_factory=list,
        description="0-4 concise correction notes or fixes that were needed",
    )
    final_notes: list[str] = Field(
        default_factory=list,
        description="1-3 final quality notes",
    )
    corrected_tailoring: Optional[TailoringOutput] = Field(
        default=None,
        description="Null when no tailoring changes are needed; otherwise corrected tailoring fields",
    )


class ResumeGenerationOutput(_StrictBase):
    """Schema for the ResumeGenerationAgent."""

    professional_summary: str = Field(
        default="",
        description="2-4 sentence final summary for the tailored resume using only grounded claims",
    )
    highlighted_skills: list[str] = Field(
        default_factory=list,
        description="4-8 skills to surface in the tailored resume",
    )
    experience_bullets: list[str] = Field(
        default_factory=list,
        description="3-6 grounded experience bullets",
    )
    section_order: list[str] = Field(
        default_factory=list,
        description="Preferred section order for the resume",
    )
    template_hint: str = Field(
        default="classic_ats",
        description="Set to classic_ats",
    )


class CoverLetterOutput(_StrictBase):
    """Schema for the CoverLetterAgent."""

    greeting: str = Field(
        default="Dear Hiring Team",
        description="Salutation such as Dear Hiring Team",
    )
    opening_paragraph: str = Field(
        default="",
        description="2-4 sentence opening paragraph grounded in the approved workflow outputs",
    )
    body_paragraphs: list[str] = Field(
        default_factory=list,
        description="1-3 grounded body paragraphs connecting evidence to the role",
    )
    closing_paragraph: str = Field(
        default="",
        description="1-2 sentence closing paragraph with grounded enthusiasm and next-step language",
    )
    signoff: str = Field(
        default="Sincerely",
        description="Closing signoff such as Sincerely",
    )
    signature_name: str = Field(
        default="",
        description="Candidate name for the signature line",
    )


# ---------------------------------------------------------------------
# Parsers (resume + JD + JD summary)
# ---------------------------------------------------------------------


class ResumeParserExperienceEntry(_StrictBase):
    title: str = Field(default="")
    organization: str = Field(default="")
    location: str = Field(default="")
    start: str = Field(default="")
    end: str = Field(default="")
    description: str = Field(default="")


class ResumeParserProjectEntry(_StrictBase):
    title: str = Field(default="")
    description: str = Field(default="")
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    start: str = Field(default="")
    end: str = Field(default="")
    links: list[str] = Field(default_factory=list)


class ResumeParserEducationEntry(_StrictBase):
    institution: str = Field(default="")
    degree: str = Field(default="")
    field_of_study: str = Field(default="")
    start: str = Field(default="")
    end: str = Field(default="")


class ResumeParserOutput(_StrictBase):
    """Schema for ``ResumeLLMParserService.parse``."""

    full_name: str = Field(default="")
    location: str = Field(default="")
    contact_lines: list[str] = Field(default_factory=list)
    summary: str = Field(default="")
    skills: list[str] = Field(default_factory=list)
    experience: list[ResumeParserExperienceEntry] = Field(default_factory=list)
    projects: list[ResumeParserProjectEntry] = Field(default_factory=list)
    education: list[ResumeParserEducationEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    publications: list[str] = Field(default_factory=list)
    source_signals: list[str] = Field(default_factory=list)


class JDParserOutput(_StrictBase):
    """Schema for ``JobDescriptionLLMParserService.parse``."""

    title: str = Field(default="")
    location: str = Field(default="")
    salary: str = Field(default="")
    experience_requirement: str = Field(default="")
    hard_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    must_haves: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)


class JDSummarySection(_StrictBase):
    title: str
    items: list[str] = Field(default_factory=list)


class JDSummaryOutput(_StrictBase):
    """Schema for ``generate_job_summary_view``.

    The summary view returns 2-4 sections, each with 2-6 bullet
    items. We leave the constraints as soft (prompt-described) so
    bulleted JDs with three real sections don't trigger schema
    failures.
    """

    sections: list[JDSummarySection] = Field(default_factory=list)


# ---------------------------------------------------------------------
# Resume builder (conversational intake + structuring)
# ---------------------------------------------------------------------


class ResumeBuilderDraftUpdates(_StrictBase):
    """Partial resume-builder draft update — every field optional.

    The intake LLM emits whichever fields it just heard the user
    mention in this turn. We use ``Optional`` rather than required
    so a turn that captured only ``target_role`` produces a valid
    payload.
    """

    full_name: Optional[str] = None
    location: Optional[str] = None
    contact_lines: Optional[list[str]] = None
    target_role: Optional[str] = None
    professional_summary: Optional[str] = None
    experience_notes: Optional[str] = None
    education_notes: Optional[str] = None
    skills: Optional[list[str]] = None
    certifications: Optional[list[str]] = None
    projects_notes: Optional[str] = None
    publications: Optional[list[str]] = None


class ResumeBuilderTurnOutput(_StrictBase):
    """Schema for ``build_resume_builder_prompt``'s intake turn."""

    draft_updates: ResumeBuilderDraftUpdates = Field(
        default_factory=ResumeBuilderDraftUpdates
    )
    assistant_message: str = Field(default="")
    status: str = Field(
        default="collecting",
        description="One of 'collecting' / 'reviewing' / 'ready'",
    )
    focus_field: str = Field(default="")


class ResumeBuilderStructuringExperienceEntry(_StrictBase):
    title: str = Field(default="")
    organization: str = Field(default="")
    location: str = Field(default="")
    start: str = Field(default="")
    end: str = Field(default="")
    bullets: list[str] = Field(default_factory=list)


class ResumeBuilderStructuringEducationEntry(_StrictBase):
    institution: str = Field(default="")
    degree: str = Field(default="")
    field_of_study: str = Field(default="")
    start: str = Field(default="")
    end: str = Field(default="")


class ResumeBuilderStructuringProjectEntry(_StrictBase):
    name: str = Field(default="")
    description: str = Field(default="")
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    start: str = Field(default="")
    end: str = Field(default="")
    link: str = Field(default="")


class ResumeBuilderStructuringOutput(_StrictBase):
    """Schema for ``build_resume_builder_structuring_prompt``.

    ``skill_categories`` is a free-form dict of category-label →
    skill-list. Using ``dict[str, list[str]]`` keeps the schema
    flexible — the prompt picks domain-appropriate buckets at
    runtime and OpenAI's structured outputs accepts the
    ``additionalProperties`` value-type without enumerating keys.
    """

    experience: list[ResumeBuilderStructuringExperienceEntry] = Field(
        default_factory=list
    )
    education: list[ResumeBuilderStructuringEducationEntry] = Field(
        default_factory=list
    )
    projects: list[ResumeBuilderStructuringProjectEntry] = Field(
        default_factory=list
    )
    skill_categories: dict[str, list[str]] = Field(default_factory=dict)
    professional_summary: str = Field(default="")


__all__ = [
    "TailoringOutput",
    "ReviewOutput",
    "ResumeGenerationOutput",
    "CoverLetterOutput",
    "ResumeParserOutput",
    "ResumeParserExperienceEntry",
    "ResumeParserEducationEntry",
    "ResumeParserProjectEntry",
    "JDParserOutput",
    "JDSummaryOutput",
    "JDSummarySection",
    "ResumeBuilderDraftUpdates",
    "ResumeBuilderTurnOutput",
    "ResumeBuilderStructuringOutput",
    "ResumeBuilderStructuringExperienceEntry",
    "ResumeBuilderStructuringEducationEntry",
    "ResumeBuilderStructuringProjectEntry",
]
