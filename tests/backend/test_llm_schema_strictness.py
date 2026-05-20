"""Hermetic guardrails for OpenAI structured-output schemas.

This session caught a silent-fallback bug where the resume-builder
structuring schema's ``dict[str, list[str]]`` field translated to a
JSON Schema with ``additionalProperties: <schema>`` — which OpenAI's
strict mode REJECTS at the API boundary with a 400. The exception
was caught by a broad ``except`` in the service, the regex fallback
ran instead, and the quality regression went undetected for weeks.

These tests prevent that class of bug from recurring without
requiring a live OpenAI call. They examine every Pydantic model
that's actually passed to ``run_structured_prompt`` in the
production codebase and assert two properties of the strict
JSON-Schema produced by ``_build_response_format_schema``:

1. No node has ``additionalProperties`` set to a schema dict. OpenAI
   strict mode requires ``additionalProperties: false`` everywhere
   (and the strict-mode rewriter sets it). A schema-valued
   ``additionalProperties`` means a ``dict[K, V]``-typed Pydantic
   field slipped through — refactor to a list of typed objects
   (label/value pairs) instead.

2. No node uses ``anyOf`` with multiple non-null branches. OpenAI
   strict mode rejects unions of distinct types (``Optional[T]`` is
   fine — that's a union with ``null``; ``Union[str, int]`` is not).

These checks are STATIC — they walk the schema tree produced
client-side. They don't need a network call, so they run on every
CI build. The live-API probe (which DOES hit OpenAI) lives in
``scripts/probe_openai_schemas.py`` and is run manually when
schemas change.
"""
from __future__ import annotations

from typing import Any

import pytest

from src.openai_service import _build_response_format_schema
from src.schemas_llm_outputs import (
    CoverLetterOutput,
    JDParserOutput,
    JDSummaryOutput,
    ResumeBuilderStructuringOutput,
    ResumeBuilderTurnOutput,
    ResumeGenerationOutput,
    ResumeParserOutput,
    ReviewOutput,
    TailoringOutput,
)


# Models exercised against `OpenAIService.run_structured_prompt` in
# production. New entries here belong any time a new schema is wired
# into a structured-output call site — keeping the test surface
# explicit catches new schemas without forcing test edits later.
PRODUCTION_STRUCTURED_OUTPUT_MODELS = [
    ("tailoring", TailoringOutput),
    ("review", ReviewOutput),
    ("resume_generation", ResumeGenerationOutput),
    ("cover_letter", CoverLetterOutput),
    ("jd_summary", JDSummaryOutput),
    ("resume_builder_structuring", ResumeBuilderStructuringOutput),
    ("resume_parser", ResumeParserOutput),
    ("jd_parser", JDParserOutput),
    ("resume_builder_turn", ResumeBuilderTurnOutput),
]


def _walk_schema(node: Any, *, path: str = "$"):
    """Yield (path, node) pairs for every dict node in the schema."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk_schema(value, path=f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_schema(value, path=f"{path}[{index}]")


@pytest.mark.parametrize(
    "task_name,model_cls",
    PRODUCTION_STRUCTURED_OUTPUT_MODELS,
    ids=[task_name for task_name, _ in PRODUCTION_STRUCTURED_OUTPUT_MODELS],
)
def test_schema_has_no_arbitrary_key_dict(task_name: str, model_cls):
    """Walk the strict-mode JSON Schema and assert no node has a
    schema-valued ``additionalProperties`` (the ``dict[K, V]`` trap).

    OpenAI strict mode lets ``additionalProperties: false`` through
    (that's what the rewriter sets on every object) but REJECTS
    ``additionalProperties: <schema-dict>`` when the parent is in a
    ``required`` array. The Pydantic-to-JSON-Schema bridge emits the
    schema-dict shape for ``dict[K, V]`` typed fields, which is what
    silently broke the resume-builder structuring call.

    If this fails: refactor the offending field to a list of typed
    objects, e.g. ``list[KeyValueBucket]`` where ``KeyValueBucket``
    has explicit ``label`` and ``value`` fields. See
    ``ResumeBuilderStructuringSkillBucket`` for the canonical
    example.
    """
    schema = _build_response_format_schema(model_cls)
    bad: list[str] = []
    for path, node in _walk_schema(schema):
        ap = node.get("additionalProperties")
        if isinstance(ap, dict):
            bad.append(f"{path}: additionalProperties is a schema dict -> {ap}")
    assert not bad, (
        f"{model_cls.__name__} has dict[K, V] field(s) that OpenAI strict "
        f"mode rejects:\n  " + "\n  ".join(bad)
    )


@pytest.mark.parametrize(
    "task_name,model_cls",
    PRODUCTION_STRUCTURED_OUTPUT_MODELS,
    ids=[task_name for task_name, _ in PRODUCTION_STRUCTURED_OUTPUT_MODELS],
)
def test_schema_has_no_multi_branch_unions(task_name: str, model_cls):
    """Walk the strict-mode JSON Schema and assert no node has an
    ``anyOf`` array with more than one non-null branch.

    OpenAI strict mode allows ``Optional[T]`` (rendered as
    ``anyOf: [<T schema>, {"type": "null"}]``) but rejects multi-
    type unions (``Union[str, int]``, ``str | None | int``, etc).
    Multi-branch unions are typically a sign the schema should be
    split or the field should be a discriminated union.
    """
    schema = _build_response_format_schema(model_cls)
    bad: list[str] = []
    for path, node in _walk_schema(schema):
        any_of = node.get("anyOf")
        if isinstance(any_of, list):
            non_null = [
                branch
                for branch in any_of
                if isinstance(branch, dict)
                and branch.get("type") != "null"
            ]
            if len(non_null) > 1:
                bad.append(
                    f"{path}: anyOf has {len(non_null)} non-null branches"
                )
    assert not bad, (
        f"{model_cls.__name__} uses a multi-branch union that OpenAI "
        f"strict mode rejects:\n  " + "\n  ".join(bad)
    )
