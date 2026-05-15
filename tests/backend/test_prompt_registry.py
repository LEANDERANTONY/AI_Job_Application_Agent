"""Prompt registry loader + cache tests.

Pins the contract the agents will rely on once each prompt is migrated
from the in-code Python string to a JSON file:

  * ``get_prompt(name)`` resolves the registry pointer and returns the
    versioned template.
  * ``get_prompt(name, version=...)`` lets the caller pin a specific
    version for A/B testing without flipping the pointer.
  * The mtime watch picks up a JSON edit between calls in dev (the
    default ``AIJOBAGENT_PROMPT_REGISTRY_DISABLE_RELOAD`` is off).
  * Malformed JSON, missing required fields, and version-filename
    mismatches surface as ``PromptValidationError``.
  * Missing prompt names raise ``PromptNotFoundError`` — distinct from
    the validation class so the caller can discriminate.
  * ``validate_schema_ref`` returns False (and logs) when the prompt's
    schema_ref disagrees with the expected Pydantic model name; the
    happy path returns True.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from backend import prompt_registry
from backend.prompt_registry import (
    PromptNotFoundError,
    PromptValidationError,
    get_prompt,
    reset_cache,
    validate_schema_ref,
)


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    """Point the registry loader at a fresh tmp dir per test so the
    in-process cache + the on-disk state stay test-local. Returns the
    Path so tests can write fixture JSON into it.

    Pin both env-driven knobs:
      - AIJOBAGENT_PROMPT_REGISTRY_ROOT: the directory we just minted.
        ``_registry_root()`` reads this at lookup time (env override)
        so a plain ``setenv`` is enough — no need to monkeypatch a
        module-level constant.
      - AIJOBAGENT_PROMPT_REGISTRY_DISABLE_RELOAD: cleared so the mtime
        watch always runs in tests. Without this, a developer's local
        env that disabled reload (legit in production) would make the
        cache-invalidation test silently fall back to the cached
        template and pass even when the fix is broken. CodeRabbit
        finding on PR #3.
    """
    monkeypatch.setenv("AIJOBAGENT_PROMPT_REGISTRY_ROOT", str(tmp_path))
    monkeypatch.setenv("AIJOBAGENT_PROMPT_REGISTRY_DISABLE_RELOAD", "")
    # _DISABLE_RELOAD was captured at module import — pin the
    # in-memory constant too so tests don't depend on whether this
    # module was reloaded after the setenv.
    monkeypatch.setattr(prompt_registry, "_DISABLE_RELOAD", False)
    reset_cache()
    yield tmp_path
    reset_cache()


def _write_prompt(
    root: Path,
    name: str,
    version: str,
    *,
    owner: str = "tailoring_agent",
    schema_ref: str = "TailoringOutput",
    system: str = "You are the Tailoring Agent.",
    metadata: dict | None = None,
) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    file_path = directory / f"{version}.json"
    file_path.write_text(
        json.dumps(
            {
                "version": version,
                "owner": owner,
                "schema_ref": schema_ref,
                "system": system,
                "metadata": metadata or {},
            }
        ),
        encoding="utf-8",
    )
    return file_path


def _write_registry(root: Path, pointers: dict[str, str]) -> Path:
    file_path = root / "registry.json"
    file_path.write_text(json.dumps(pointers), encoding="utf-8")
    return file_path


# ────────────────────────────────────────────────────────────────────
# Happy path
# ────────────────────────────────────────────────────────────────────


def test_get_prompt_resolves_current_version_from_registry(isolated_registry):
    _write_prompt(
        isolated_registry,
        "tailoring",
        "v1",
        system="You are the Tailoring Agent. v1 wording.",
    )
    _write_registry(isolated_registry, {"tailoring": "v1"})

    template = get_prompt("tailoring")

    assert template.name == "tailoring"
    assert template.version == "v1"
    assert template.owner == "tailoring_agent"
    assert template.schema_ref == "TailoringOutput"
    assert "v1 wording" in template.system


def test_get_prompt_with_explicit_version_overrides_registry_pointer(
    isolated_registry,
):
    """A caller can pin a specific version (e.g. for A/B testing) by
    passing ``version=`` without flipping the registry pointer."""
    _write_prompt(
        isolated_registry,
        "tailoring",
        "v1",
        system="v1 wording",
    )
    _write_prompt(
        isolated_registry,
        "tailoring",
        "v2",
        system="v2 wording",
    )
    _write_registry(isolated_registry, {"tailoring": "v1"})

    template_default = get_prompt("tailoring")
    template_pinned = get_prompt("tailoring", version="v2")

    assert "v1 wording" in template_default.system
    assert "v2 wording" in template_pinned.system


def test_get_prompt_returns_metadata_unchanged(isolated_registry):
    """The free-form metadata blob is passed through verbatim so a
    prompt author can attach ``description``, ``previous_version``,
    or any other slot they want."""
    _write_prompt(
        isolated_registry,
        "tailoring",
        "v1",
        metadata={
            "description": "Tailoring agent system prompt.",
            "previous_version": "n/a",
            "notes": "Initial migration from src/prompts.py",
        },
    )
    _write_registry(isolated_registry, {"tailoring": "v1"})

    template = get_prompt("tailoring")
    assert template.metadata["description"] == "Tailoring agent system prompt."
    assert template.metadata["previous_version"] == "n/a"
    assert "Initial migration" in template.metadata["notes"]


# ────────────────────────────────────────────────────────────────────
# Caching + reload
# ────────────────────────────────────────────────────────────────────


def test_get_prompt_caches_repeated_lookups(isolated_registry):
    """Repeated calls for the same (name, version) should not re-read
    the JSON from disk — the cached PromptTemplate object is the
    canonical answer until mtime changes."""
    _write_prompt(isolated_registry, "tailoring", "v1")
    _write_registry(isolated_registry, {"tailoring": "v1"})

    first = get_prompt("tailoring")
    second = get_prompt("tailoring")

    assert first is second  # same object — cached, not re-read


def test_mtime_change_picks_up_new_system_text(isolated_registry):
    """Editing the JSON file between calls should result in the next
    get_prompt seeing the new text (without needing a process restart).
    """
    file_path = _write_prompt(
        isolated_registry,
        "tailoring",
        "v1",
        system="original wording",
    )
    _write_registry(isolated_registry, {"tailoring": "v1"})

    first = get_prompt("tailoring")
    assert "original wording" in first.system

    # Force a mtime bump and rewrite the file. ``time.sleep(1)`` here
    # because filesystems can have second-resolution mtime; without it
    # the test would flake on systems with coarse stat granularity.
    time.sleep(1.05)
    file_path.write_text(
        json.dumps(
            {
                "version": "v1",
                "owner": "tailoring_agent",
                "schema_ref": "TailoringOutput",
                "system": "new wording",
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )

    second = get_prompt("tailoring")
    assert "new wording" in second.system


# ────────────────────────────────────────────────────────────────────
# Error surfaces
# ────────────────────────────────────────────────────────────────────


def test_missing_prompt_name_raises_not_found(isolated_registry):
    _write_registry(isolated_registry, {})  # registry exists but is empty
    with pytest.raises(PromptNotFoundError):
        get_prompt("nope")


def test_missing_version_file_raises_not_found(isolated_registry):
    _write_registry(isolated_registry, {"tailoring": "v99"})
    # registry points at v99 but no v99.json on disk
    with pytest.raises(PromptNotFoundError):
        get_prompt("tailoring")


def test_explicit_missing_version_raises_not_found(isolated_registry):
    _write_prompt(isolated_registry, "tailoring", "v1")
    _write_registry(isolated_registry, {"tailoring": "v1"})
    with pytest.raises(PromptNotFoundError):
        get_prompt("tailoring", version="v999")


def test_malformed_json_raises_validation_error(isolated_registry):
    _write_registry(isolated_registry, {"tailoring": "v1"})
    bad_path = isolated_registry / "tailoring" / "v1.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("not valid json {", encoding="utf-8")
    with pytest.raises(PromptValidationError):
        get_prompt("tailoring")


def test_missing_required_field_raises_validation_error(isolated_registry):
    _write_registry(isolated_registry, {"tailoring": "v1"})
    bad_path = isolated_registry / "tailoring" / "v1.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text(
        json.dumps({"version": "v1", "owner": "x"}),  # missing schema_ref + system
        encoding="utf-8",
    )
    with pytest.raises(PromptValidationError):
        get_prompt("tailoring")


def test_version_filename_mismatch_raises_validation_error(isolated_registry):
    """If a prompt JSON file says ``version: v2`` but lives at
    ``v1.json``, the registry has a footgun — surfacing it loudly at
    load time beats letting it silently load the wrong content."""
    _write_registry(isolated_registry, {"tailoring": "v1"})
    bad_path = isolated_registry / "tailoring" / "v1.json"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text(
        json.dumps(
            {
                "version": "v2",
                "owner": "x",
                "schema_ref": "X",
                "system": "x",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PromptValidationError):
        get_prompt("tailoring")


def test_registry_pointer_file_missing_raises_validation_error(
    isolated_registry,
):
    # No registry.json at all
    with pytest.raises(PromptValidationError):
        get_prompt("tailoring")


def test_empty_prompt_name_raises_validation_error(isolated_registry):
    _write_registry(isolated_registry, {})
    with pytest.raises(PromptValidationError):
        get_prompt("")


# ────────────────────────────────────────────────────────────────────
# Schema ref cross-check
# ────────────────────────────────────────────────────────────────────


def test_validate_schema_ref_returns_true_on_match(isolated_registry):
    _write_prompt(
        isolated_registry,
        "tailoring",
        "v1",
        schema_ref="TailoringOutput",
    )
    _write_registry(isolated_registry, {"tailoring": "v1"})

    assert validate_schema_ref("tailoring", "TailoringOutput") is True


def test_validate_schema_ref_returns_false_on_mismatch(isolated_registry, caplog):
    _write_prompt(
        isolated_registry,
        "tailoring",
        "v1",
        schema_ref="TailoringOutput",
    )
    _write_registry(isolated_registry, {"tailoring": "v1"})

    with caplog.at_level("WARNING"):
        result = validate_schema_ref("tailoring", "SomethingElse")
    assert result is False
    assert any(
        "schema_ref_mismatch" in record.message
        for record in caplog.records
    )
