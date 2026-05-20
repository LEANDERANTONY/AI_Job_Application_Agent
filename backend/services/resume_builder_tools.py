"""Tools available to the resume-builder conversational agent.

Slice 1A of the "Résumé-builder → tool-using agentic loop" plan
(report.md, parked 2026-05-20).

The conversational intake LLM is given a small toolbox so it can do
things it previously hallucinated — fetching a GitHub README is the
first one. The pattern is the Responses-API native function-calling
loop: the LLM emits a `function_call` item naming a tool, the server
executes it via the registry, the tool's output is fed back as a
`function_call_output` item, and the loop continues until the LLM
emits a final text response.

This module is the IMPLEMENTATION side of the contract. The
agentic-loop driver lives in ``src/openai_service.run_tool_loop`` and
is wired into the resume-builder service at
``backend/services/resume_builder_service._run_llm_turn``.

Design notes / safety:

- Each tool returns a JSON-serializable dict (success) or an error
  dict the model can read and act on (e.g. "fetch failed — ask the
  user for the README instead"). We never raise exceptions across the
  tool boundary — failures are first-class outputs the model is
  trained to handle.
- The fetch tool only allows ``github.com`` URLs and only reads
  ``raw.githubusercontent.com`` (the static-content CDN). No POST, no
  cookies, no auth headers — read-only, public content only.
- Size + timeout caps stay tight (200 KB, 6 s) so a hostile URL can't
  blow latency or memory. The whole tool call has to come back in
  well under the conversational turn budget.
- The tool body is HERMETIC under test — ``_fetch_text`` is the only
  network call site, monkeypatched in tests to return canned bytes.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

import requests


LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# fetch_github_readme
# ---------------------------------------------------------------------------

# Hard caps. The README body is fed into the LLM context — a 200 KB
# README is already at the edge of what we want to spend tokens on, and
# 6 seconds is a hard ceiling on conversational-turn latency before the
# UI feels broken.
_README_MAX_BYTES = 200 * 1024
_README_TIMEOUT_SECONDS = 6.0
# raw.githubusercontent.com serves text/plain regardless of source
# extension. We accept both text/plain and text/markdown defensively.
_ACCEPTABLE_CONTENT_TYPES = ("text/plain", "text/markdown")

# raw.githubusercontent.com resolves /{owner}/{repo}/HEAD/... to the
# default branch of the repo. We use that instead of guessing
# main/master/etc.
_RAW_README_URL = (
    "https://raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md"
)

# We accept a few common shapes for the GitHub URL the user might paste:
#   github.com/owner/repo
#   github.com/owner/repo/
#   github.com/owner/repo/tree/main
#   github.com/owner/repo/blob/main/README.md
# Everything past /{owner}/{repo} is ignored — we always fetch the
# default-branch README.
_GITHUB_PATH_PATTERN = re.compile(
    r"^/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}[A-Za-z0-9])?)"
    r"/(?P<repo>[A-Za-z0-9_.-]+?)(?:/|$)"
)


@dataclass(frozen=True)
class _GitHubRepoRef:
    owner: str
    repo: str


def _parse_github_url(url: str) -> _GitHubRepoRef | None:
    """Validate and parse a public GitHub URL into (owner, repo).

    Returns None for any URL that isn't a https://github.com/owner/repo
    shape. We deliberately reject http://, IP-literal hosts, and
    github.io / gist.github.com / api.github.com / etc. — only the
    canonical web host is in scope for this tool.
    """
    cleaned = str(url or "").strip()
    if not cleaned:
        return None
    # Allow the user to paste without the scheme; default to https.
    if not cleaned.lower().startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        return None
    if parsed.scheme != "https":
        return None
    if (parsed.hostname or "").lower() != "github.com":
        return None
    match = _GITHUB_PATH_PATTERN.match(parsed.path or "")
    if not match:
        return None
    # Strip a trailing ".git" — github accepts both /{owner}/{repo} and
    # /{owner}/{repo}.git, but raw.githubusercontent.com only knows the
    # bare form.
    repo = match.group("repo")
    if repo.endswith(".git"):
        repo = repo[: -len(".git")]
    return _GitHubRepoRef(owner=match.group("owner"), repo=repo)


def _fetch_text(url: str, *, timeout: float, max_bytes: int) -> dict:
    """Single network call site. Tests monkeypatch this.

    Returns a dict shaped:
      {"status": int, "content_type": str, "body": str}
    on success, or
      {"error": "...", "details": "..."}
    on failure. Never raises across the boundary.
    """
    try:
        response = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            # raw.githubusercontent.com returns text — we don't need
            # any of the github.com auth/session cookies, and we don't
            # send a custom UA so we look like a vanilla client.
            headers={"Accept": "text/plain, text/markdown, */*;q=0.5"},
            stream=True,
        )
    except requests.Timeout:
        return {"error": "timeout", "details": f"Fetch exceeded {timeout:.0f}s."}
    except requests.RequestException as exc:
        return {"error": "network_error", "details": str(exc)[:200]}

    try:
        status = int(getattr(response, "status_code", 0) or 0)
        content_type = (response.headers.get("Content-Type") or "").lower()
        if status != 200:
            return {
                "error": "http_status",
                "details": f"HTTP {status} from {url}.",
            }
        # Reject non-text content before reading the body — saves us
        # from streaming a binary blob into memory.
        if not any(ct in content_type for ct in _ACCEPTABLE_CONTENT_TYPES):
            return {
                "error": "wrong_content_type",
                "details": f"Expected text/markdown or text/plain, got {content_type or 'unknown'}.",
            }
        # Read in a single chunk capped at max_bytes + 1 so we can
        # detect oversize content without buffering the whole body.
        # ``response.raw`` is the urllib3 HTTPResponse — calling
        # .read(N) returns at most N bytes.
        raw_bytes = response.raw.read(max_bytes + 1, decode_content=True)
        if raw_bytes is None:
            return {"error": "empty_body", "details": "No body returned."}
        if len(raw_bytes) > max_bytes:
            return {
                "error": "oversize",
                "details": f"README exceeds {max_bytes} bytes.",
            }
        try:
            body_text = raw_bytes.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError) as exc:
            return {"error": "decode_error", "details": str(exc)[:200]}
        return {"status": status, "content_type": content_type, "body": body_text}
    finally:
        try:
            response.close()
        except Exception:  # pragma: no cover - defensive
            pass


def fetch_github_readme(url: str) -> dict:
    """Read the default-branch README.md of a public GitHub repo.

    Inputs:
      url: A https://github.com/{owner}/{repo} URL.

    Returns one of:
      {"ok": True, "url": str, "owner": str, "repo": str, "readme": str}
      {"ok": False, "error": str, "message": str}

    The ``error`` codes are stable string keys so the LLM can switch on
    them without prompt drift:
      - "invalid_url"        — couldn't parse to github.com/owner/repo
      - "timeout"            — fetch took too long
      - "network_error"      — connection failed
      - "http_status"        — non-200 (e.g. 404 for a private/missing repo)
      - "wrong_content_type" — server returned non-text content
      - "oversize"           — README too large to ingest
      - "empty_body"         — 200 with no body (shouldn't happen)
      - "decode_error"       — README is not valid utf-8 text
    """
    ref = _parse_github_url(url)
    if ref is None:
        return {
            "ok": False,
            "error": "invalid_url",
            "message": (
                "URL must be a public github.com/{owner}/{repo} link. "
                "Ask the user to paste a github.com URL, or to describe "
                "the project's tech stack and outcomes directly."
            ),
        }
    raw_url = _RAW_README_URL.format(owner=ref.owner, repo=ref.repo)
    fetch_result = _fetch_text(
        raw_url,
        timeout=_README_TIMEOUT_SECONDS,
        max_bytes=_README_MAX_BYTES,
    )
    if "error" in fetch_result:
        return {
            "ok": False,
            "error": fetch_result["error"],
            "message": (
                "Could not fetch the README. Ask the user to share the "
                "project's tech stack and outcomes directly instead. "
                f"({fetch_result.get('details', '')})"
            ).strip(),
        }
    return {
        "ok": True,
        "url": raw_url,
        "owner": ref.owner,
        "repo": ref.repo,
        "readme": fetch_result["body"],
    }


# ---------------------------------------------------------------------------
# Responses-API tool registry
# ---------------------------------------------------------------------------

# Tool spec in the shape the OpenAI Responses API expects. The
# ``function`` key carries the JSON Schema for the tool's arguments —
# the LLM uses this to construct valid arguments without guessing.
FETCH_GITHUB_README_TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "name": "fetch_github_readme",
    "description": (
        "Fetch the default-branch README.md of a PUBLIC GitHub repository "
        "the user mentioned. Use this when the user pastes a github.com URL "
        "and you need to know what the project does, what tech stack it "
        "uses, or what outcomes to surface on the resume. On failure, "
        "ask the user to describe the project directly instead — never "
        "fabricate details."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "url": {
                "type": "string",
                "description": (
                    "Full public GitHub URL, e.g. "
                    "'https://github.com/openai/openai-python'. Must be a "
                    "github.com host — github.io, gist.github.com, and "
                    "api.github.com are not supported."
                ),
            },
        },
        "required": ["url"],
    },
}


# ---------------------------------------------------------------------------
# web_search (FUNCTION-wrapped, dispatches to OpenAI's built-in web_search)
# ---------------------------------------------------------------------------
#
# Why this is wrapped as a function tool instead of being a raw
# {"type": "web_search"} server-side tool: OpenAI's API rejects
# combining ``web_search`` with ``text.format = json_object`` —
# the 400 reads "Web Search cannot be used with JSON mode." Our
# main intake loop NEEDS json_object (we return a structured envelope
# with draft_updates / assistant_message / status / etc.), so we
# can't put web_search on the same call.
#
# The wrap: the agent calls ``web_search(query)`` like any other
# function tool. The dispatcher makes a SEPARATE internal
# responses.create call — no json_object format, with OpenAI's
# built-in web_search enabled — and returns the synthesized text as
# the function_call_output. Main loop stays JSON-mode safe; the
# agent gets a research capability on-demand.
#
# Cost shape: each ``web_search`` invocation is ONE extra
# responses.create call (so two API calls per search round-trip:
# the model decides to search, the dispatcher fires the search,
# the model uses the result on the next iteration). The prompt
# tells the agent to use this SPARINGLY, so realistic usage is
# 0–2 web_search calls per session.
#
# Search execution itself runs on OpenAI infrastructure (US-hosted).
# Our EU-data-residency posture (docs/competitive-landscape.md)
# applies to user data we store, not to outbound research queries
# — so this is acceptable for v1. Revisit when ADR-028 D1 multi-
# provider eval lands and a concrete EU alternative exists.
WEB_SEARCH_TIMEOUT_SECONDS = 30.0
# Hard cap on the synthesized result string — searches can return
# long answers, and we feed the result back into the main loop's
# input list (which we want to keep manageable). 8KB ≈ ~2k tokens,
# enough for a research summary, small enough not to bloat history.
WEB_SEARCH_MAX_RESULT_CHARS = 8 * 1024


def _web_search(
    query: str,
    *,
    openai_service: Any | None = None,
) -> dict:
    """Run a web_search via OpenAI's built-in tool and return the
    synthesized text result.

    Routed through a fresh ``responses.create`` call WITHOUT json
    mode so OpenAI's strict-mode check doesn't reject the combination.
    The model in this inner call is small + cheap (the search
    synthesis doesn't need the main intake model's reasoning depth);
    we hard-code ``gpt-5.4-mini`` to keep latency + cost predictable.

    Returns ``{"ok": True, "result": str, "query": str}`` on success
    or ``{"ok": False, "error": str, "message": str}`` on failure.
    Like ``fetch_github_readme``, errors are first-class outputs —
    never raised across the tool boundary.
    """
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        return {
            "ok": False,
            "error": "empty_query",
            "message": "web_search needs a non-empty query.",
        }
    if openai_service is None or not getattr(openai_service, "is_available", lambda: False)():
        return {
            "ok": False,
            "error": "no_openai_service",
            "message": (
                "Web search requires an OpenAI client. Ask the user "
                "to describe the external context directly."
            ),
        }
    client = getattr(openai_service, "_client", None)
    if client is None:
        return {
            "ok": False,
            "error": "no_openai_client",
            "message": "OpenAI client is not initialized.",
        }

    try:
        response = client.responses.create(
            model="gpt-5.4-mini",
            instructions=(
                "You are a research assistant. Use the web_search tool to "
                "answer the user's question with concrete sources. Cite the "
                "source domain inline. Keep the answer short — 4 sentences "
                "max. If the search returns nothing useful, say so plainly "
                "instead of inventing."
            ),
            input=cleaned_query,
            store=False,
            max_output_tokens=600,
            tools=[{"type": "web_search"}],
            tool_choice="auto",
        )
    except Exception as exc:
        LOGGER.exception("web_search dispatch failed.")
        return {
            "ok": False,
            "error": "search_dispatch_failed",
            "message": f"{type(exc).__name__}: {exc}"[:240],
        }

    # Extract the synthesized text. The inner response can carry both
    # ``web_search_call`` items (OpenAI's record of the search) and
    # ``message`` items containing the answer text. We only need the
    # text — the search-call items are an implementation detail.
    collected: list[str] = []
    for item in getattr(response, "output", None) or []:
        item_type = getattr(item, "type", None)
        if isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "message":
            continue
        content = (
            item.content
            if not isinstance(item, dict)
            else item.get("content")
        ) or []
        for part in content:
            part_type = getattr(part, "type", None)
            if isinstance(part, dict):
                part_type = part.get("type")
            if part_type == "output_text":
                text = (
                    part.text
                    if not isinstance(part, dict)
                    else part.get("text")
                )
                if text:
                    collected.append(str(text))
    result_text = "\n".join(collected).strip()
    if not result_text:
        return {
            "ok": False,
            "error": "empty_result",
            "message": "Search returned no synthesized text.",
        }
    if len(result_text) > WEB_SEARCH_MAX_RESULT_CHARS:
        result_text = (
            result_text[: WEB_SEARCH_MAX_RESULT_CHARS].rstrip()
            + "…[truncated]"
        )
    return {"ok": True, "query": cleaned_query, "result": result_text}


WEB_SEARCH_TOOL_SPEC: dict[str, Any] = {
    "type": "function",
    "name": "web_search",
    "description": (
        "Search the web (via OpenAI's built-in search) for EXTERNAL CONTEXT "
        "the user is asking about — company profile, role expectations, "
        "industry norms, what a specific employer typically looks for on a "
        "resume. Returns a short synthesized answer with source attribution. "
        "Use SPARINGLY: don't search for info the user already shared, don't "
        "search for generic resume advice, don't search for speculative "
        "questions like 'what salary will I get'. The query should be "
        "specific and short — one focused question, not a paragraph."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "A specific, focused search query — e.g. 'Senior MLE "
                    "role expectations at Anthropic 2026' or 'standard "
                    "sections on a fintech compliance resume'."
                ),
            },
        },
        "required": ["query"],
    },
}


RESUME_BUILDER_TOOL_SPECS: list[dict[str, Any]] = [
    FETCH_GITHUB_README_TOOL_SPEC,
    WEB_SEARCH_TOOL_SPEC,
]


# Internal registry — maps the Responses-API ``name`` field on a
# function_call item to the Python callable that implements it.
_TOOL_IMPLEMENTATIONS: dict[str, Callable[..., dict]] = {
    "fetch_github_readme": fetch_github_readme,
    "web_search": _web_search,
}


# Tools that need the ``OpenAIService`` injected into their call (set
# by name to avoid signature introspection at hot-path execute time).
# ``_web_search`` needs it to fire its inner ``responses.create`` for
# the search; ``fetch_github_readme`` is HTTP-only and doesn't.
_TOOLS_REQUIRING_OPENAI: frozenset[str] = frozenset({"web_search"})


def execute_tool(
    name: str,
    arguments_json: str,
    *,
    openai_service: Any | None = None,
) -> str:
    """Dispatch a Responses-API function_call to the matching tool.

    Inputs:
      name: The function name the LLM asked for.
      arguments_json: Raw JSON string of arguments. The Responses API
        always passes arguments as a JSON-encoded string; we parse it
        here so each tool can sign its own typed signature.
      openai_service: Optional OpenAIService instance. Forwarded only
        to tools that declare in ``_TOOLS_REQUIRING_OPENAI`` that they
        need it (e.g. ``web_search``, which makes its own internal
        ``responses.create`` call to use OpenAI's built-in search
        tool from outside JSON mode).

    Returns a string. The agentic-loop driver attaches this string to a
    ``function_call_output`` item, which is fed back to the model on
    the next iteration. We always emit a JSON-encoded string so the
    model can reason about a structured result. Errors are returned —
    never raised — so the loop can continue.
    """
    impl = _TOOL_IMPLEMENTATIONS.get(name)
    if impl is None:
        return json.dumps(
            {
                "ok": False,
                "error": "unknown_tool",
                "message": f"No tool named {name!r} is registered.",
            }
        )
    try:
        args: dict = json.loads(arguments_json or "{}")
    except (TypeError, ValueError) as exc:
        return json.dumps(
            {
                "ok": False,
                "error": "invalid_arguments",
                "message": f"Could not parse arguments JSON: {exc}",
            }
        )
    if not isinstance(args, dict):
        return json.dumps(
            {
                "ok": False,
                "error": "invalid_arguments",
                "message": "Arguments must be a JSON object.",
            }
        )
    if name in _TOOLS_REQUIRING_OPENAI:
        # Inject as a kwarg so the tool's signature can declare it
        # explicitly (and so a model-emitted ``openai_service`` arg
        # can't slip in via ``args`` — we always overwrite).
        args["openai_service"] = openai_service
    try:
        result = impl(**args)
    except TypeError as exc:
        # Wrong arguments shape — surface as a tool error so the model
        # can adjust on the next iteration instead of crashing the run.
        return json.dumps(
            {
                "ok": False,
                "error": "invalid_arguments",
                "message": f"Tool rejected arguments: {exc}",
            }
        )
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.exception(
            "Resume-builder tool %s raised unexpectedly.", name
        )
        return json.dumps(
            {
                "ok": False,
                "error": "tool_exception",
                "message": f"Tool raised {type(exc).__name__}: {exc}",
            }
        )
    if not isinstance(result, dict):
        return json.dumps({"ok": True, "result": result})
    return json.dumps(result)
