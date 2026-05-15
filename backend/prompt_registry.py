"""Versioned JSON prompt registry.

The system prompts driving each agent / service used to live as Python
string constants scattered across ``src/prompts.py``,
``src/services/jd_summary_service.py``, and
``backend/services/resume_builder_service.py``. That makes prompt
iteration painful: a 30-line tweak shows up as a 30-line diff inside a
1200-line Python file, mixed in with control flow.

This registry pulls the canonical prompt content out into one JSON
file per (prompt_name, version) pair under ``prompts/``. Each file
carries:

    {
      "version":      "v1",
      "owner":        "tailoring_agent",     # Python module that uses it
      "schema_ref":   "TailoringOutput",     # Pydantic model name (str ref)
      "system":       "<system prompt text>",
      "metadata":     { ... }                # optional free-form notes
    }

Plus a single ``prompts/registry.json`` that maps each prompt_name to
its CURRENT version. Bumping a prompt is two file changes:
  1. Drop a new ``vN.json`` next to the existing one.
  2. Update ``registry.json`` to point at the new version.

A migration path exists: the loader takes an optional explicit version
so callers can A/B between v1 and v2 by passing ``version="v2"``
without flipping the registry pointer.

Dynamic user prompt building (the ``_build_budgeted_user_prompt`` glue
that interleaves serialized profile / JD / fit-analysis JSON) stays
in Python — that logic is too procedural to express cleanly in JSON.
The registry's contract is "give me the system prompt for prompt_name
at the current version"; the call site composes the user prompt from
the runtime payload.

Caching: the registry is loaded once per process and cached in
memory. In development, the file mtime is checked on each ``get_prompt``
call so an edit to a JSON file is picked up without restarting the
service. In production (when the env-var ``AIJOBAGENT_PROMPT_REGISTRY_DISABLE_RELOAD``
is truthy) the mtime check is skipped, saving a syscall per prompt
lookup.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# Resolve the prompts/ directory at the repo root. The CWD when the
# server runs depends on the deploy target (systemd unit, docker, dev
# shell), so we anchor relative to this file's location and walk up to
# the project root.
_DEFAULT_REGISTRY_ROOT = (
    Path(__file__).resolve().parent.parent / "prompts"
)


def _registry_root() -> Path:
    """Return the directory under which v* JSON files live.

    Tests can monkeypatch the env var to point at a fixture directory
    so a test prompt doesn't have to live in the production tree.

    The env override is read at LOOKUP time (each call), not at module
    import. A module-import-time read meant that setting
    AIJOBAGENT_PROMPT_REGISTRY_ROOT after the registry had already
    been imported elsewhere had no effect — which broke tests that
    used monkeypatch.setenv mid-suite, and confused operators who
    expected env-based config to behave dynamically. Codex P2 on PR #3.
    """
    override = os.getenv("AIJOBAGENT_PROMPT_REGISTRY_ROOT", "").strip()
    if override:
        return Path(override)
    return _DEFAULT_REGISTRY_ROOT


# Toggle for the file mtime watch. Useful in production where every
# prompt lookup adds an os.stat() call we'd rather avoid (the watch
# only matters for dev where someone is iterating on a prompt JSON).
_DISABLE_RELOAD = (
    os.getenv("AIJOBAGENT_PROMPT_REGISTRY_DISABLE_RELOAD", "").strip().lower()
    in {"1", "true", "yes", "on"}
)


@dataclass(frozen=True)
class PromptTemplate:
    """One immutable prompt definition.

    Returned by ``get_prompt``; callers read ``.system`` to compose
    the LLM request and ``.schema_ref`` to validate the Pydantic
    model the response will land in.

    The ``metadata`` dict is free-form. Useful slots so far:
      * ``description``: one-line summary of the prompt's intent.
      * ``previous_version``: the version this one supersedes.
      * ``notes``: longer-form rationale for the current wording.
    """

    name: str
    version: str
    owner: str
    schema_ref: str
    system: str
    metadata: dict[str, Any]


class PromptNotFoundError(LookupError):
    """Raised when ``get_prompt`` can't find a prompt or version."""


class PromptValidationError(ValueError):
    """Raised when a registry entry or version JSON is malformed."""


# Module-level cache. ``_lock`` guards mutations so concurrent calls
# from different threads (e.g. parallel workers in a uvicorn process)
# don't double-load.
_lock = threading.RLock()
_registry_cache: dict[str, str] | None = None  # prompt_name -> current version
_registry_mtime: float = 0.0
_template_cache: dict[tuple[str, str], PromptTemplate] = {}
_template_mtime: dict[tuple[str, str], float] = {}


def _load_registry_pointer() -> dict[str, str]:
    """Return the prompt_name → current_version mapping from
    ``prompts/registry.json``. Cached; re-reads on mtime change unless
    the reload knob is off."""
    global _registry_cache, _registry_mtime
    path = _registry_root() / "registry.json"
    if not path.exists():
        raise PromptValidationError(
            f"prompts/registry.json missing — expected at {path}."
        )
    with _lock:
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            raise PromptValidationError(
                f"Could not stat registry.json: {exc}"
            ) from exc
        if (
            _registry_cache is not None
            and (_DISABLE_RELOAD or mtime == _registry_mtime)
        ):
            return _registry_cache
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PromptValidationError(
                f"registry.json is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise PromptValidationError(
                "registry.json must be a top-level object mapping "
                "prompt_name → current_version."
            )
        # Coerce values to strings so callers downstream can always
        # rely on string semantics; integers would slip past unrelated
        # tests but fail when concatenated into a file path.
        registry = {str(k): str(v) for k, v in payload.items()}
        _registry_cache = registry
        _registry_mtime = mtime
        return registry


def _load_template_file(name: str, version: str) -> PromptTemplate:
    """Load ``prompts/<name>/<version>.json`` into a PromptTemplate.

    Cached per (name, version); re-reads on mtime change unless the
    reload knob is off. Raises PromptNotFoundError if the file doesn't
    exist; PromptValidationError if the JSON is missing required
    fields.
    """
    path = _registry_root() / name / f"{version}.json"
    if not path.exists():
        raise PromptNotFoundError(
            f"No prompt template found for {name!r} version {version!r} "
            f"(expected at {path})."
        )
    with _lock:
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            raise PromptValidationError(
                f"Could not stat {path}: {exc}"
            ) from exc
        cache_key = (name, version)
        cached = _template_cache.get(cache_key)
        cached_mtime = _template_mtime.get(cache_key, 0.0)
        if cached is not None and (_DISABLE_RELOAD or mtime == cached_mtime):
            return cached
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PromptValidationError(
                f"{path} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise PromptValidationError(
                f"{path} must be a top-level object."
            )
        # Validate required fields. Missing any of these is a
        # registry-author bug; raising loudly here means we catch it
        # at startup (or at test time) instead of at the call site
        # with a cryptic KeyError.
        for required in ("version", "owner", "schema_ref", "system"):
            if required not in payload:
                raise PromptValidationError(
                    f"{path} missing required field {required!r}."
                )
        if str(payload["version"]) != version:
            raise PromptValidationError(
                f"{path} version field {payload['version']!r} "
                f"does not match filename {version!r}."
            )
        # Guard metadata type: ``dict(payload.get("metadata") or {})``
        # raises TypeError when the JSON contains a list/string/number
        # under ``metadata`` instead of an object, bypassing the
        # PromptValidationError contract and surfacing as a generic
        # 500. Explicit validation gives the operator a useful error.
        # CodeRabbit Major on PR #3.
        metadata_value = payload.get("metadata")
        if metadata_value is None:
            metadata: dict[str, Any] = {}
        elif isinstance(metadata_value, dict):
            metadata = dict(metadata_value)
        else:
            raise PromptValidationError(
                f"{path} metadata must be an object, got "
                f"{type(metadata_value).__name__!s}."
            )
        template = PromptTemplate(
            name=name,
            version=str(payload["version"]),
            owner=str(payload["owner"]),
            schema_ref=str(payload["schema_ref"]),
            system=str(payload["system"]),
            metadata=metadata,
        )
        _template_cache[cache_key] = template
        _template_mtime[cache_key] = mtime
        return template


def get_prompt(name: str, version: str | None = None) -> PromptTemplate:
    """Return the PromptTemplate for ``name`` at the requested version.

    When ``version`` is None, the registry's current-version pointer
    decides. When ``version`` is set explicitly, the caller can pin to
    a specific version regardless of what the pointer says — useful
    for A/B testing a candidate prompt without flipping the pointer.

    Raises:
      PromptNotFoundError: the prompt name (or specific version) isn't
        on disk.
      PromptValidationError: the prompt JSON is malformed.
    """
    if not name:
        raise PromptValidationError("Prompt name must be a non-empty string.")
    if version is None:
        registry = _load_registry_pointer()
        if name not in registry:
            raise PromptNotFoundError(
                f"Prompt {name!r} not registered in registry.json. "
                f"Add an entry mapping {name!r} → version string."
            )
        resolved_version = registry[name]
    else:
        resolved_version = str(version)
    return _load_template_file(name, resolved_version)


def validate_schema_ref(name: str, expected_model_name: str) -> bool:
    """Best-effort cross-check that the prompt's schema_ref matches the
    Pydantic model the caller plans to validate against.

    Returns True on a match, logs a warning and returns False on a
    mismatch. We log + return rather than raise so a mismatched prompt
    doesn't crash production at the call site — the caller can decide
    whether to abort or continue. In test land this lights up before
    rollout.
    """
    template = get_prompt(name)
    if template.schema_ref != expected_model_name:
        logger.warning(
            "prompt_registry_schema_ref_mismatch name=%s schema_ref=%r expected=%r",
            name,
            template.schema_ref,
            expected_model_name,
        )
        return False
    return True


def reset_cache() -> None:
    """Test helper — wipe the in-memory cache so a fixture-driven
    prompt directory is re-read on the next ``get_prompt`` call.
    Production callers should NOT use this; the file-mtime watch is
    the right path for dev hot-reload.
    """
    global _registry_cache, _registry_mtime
    with _lock:
        _registry_cache = None
        _registry_mtime = 0.0
        _template_cache.clear()
        _template_mtime.clear()


__all__ = [
    "PromptNotFoundError",
    "PromptTemplate",
    "PromptValidationError",
    "get_prompt",
    "reset_cache",
    "validate_schema_ref",
]
