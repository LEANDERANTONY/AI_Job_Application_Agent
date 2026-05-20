"""Hermetic tests for the resume-builder tool registry.

Slice 1A: the ``fetch_github_readme`` tool. These tests monkeypatch
``backend.services.resume_builder_tools._fetch_text`` so no real
network call goes out — the unit under test is the URL parsing, the
error-classification, and the dispatcher contract.

The contract the LLM relies on:
  - Success → ``{"ok": True, ...readme: str, ...}``
  - Failure → ``{"ok": False, "error": <stable code>, "message": str}``
  - The dispatcher (``execute_tool``) always returns a JSON-encoded
    string, never raises across the tool boundary.
"""
from __future__ import annotations

import json

import pytest

from backend.services import resume_builder_tools as tools


# ---------------------------------------------------------------------------
# _parse_github_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected_owner, expected_repo",
    [
        ("https://github.com/openai/openai-python", "openai", "openai-python"),
        ("https://github.com/openai/openai-python/", "openai", "openai-python"),
        ("https://github.com/openai/openai-python/tree/main", "openai", "openai-python"),
        ("https://github.com/openai/openai-python/blob/main/README.md", "openai", "openai-python"),
        ("https://github.com/openai/openai-python.git", "openai", "openai-python"),
        # Scheme inference — paste without the protocol works.
        ("github.com/openai/openai-python", "openai", "openai-python"),
        # Names with dots / hyphens / underscores stay intact.
        ("https://github.com/some-user/some.repo_name", "some-user", "some.repo_name"),
    ],
)
def test_parse_github_url_accepts_canonical_shapes(url, expected_owner, expected_repo):
    ref = tools._parse_github_url(url)
    assert ref is not None, f"Expected to parse {url!r}"
    assert ref.owner == expected_owner
    assert ref.repo == expected_repo


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        # http:// rejected — must be https to keep the surface small.
        "http://github.com/openai/openai-python",
        # Wrong hosts.
        "https://gist.github.com/openai/abc",
        "https://api.github.com/repos/openai/openai-python",
        "https://github.io/openai/something",
        "https://google.com/openai/openai-python",
        # Missing owner/repo.
        "https://github.com/",
        "https://github.com/openai",
        "https://github.com/openai/",
        # IP-literal host (defense in depth — the regex would also reject).
        "https://127.0.0.1/openai/openai-python",
    ],
)
def test_parse_github_url_rejects_non_github_or_malformed(url):
    assert tools._parse_github_url(url) is None


# ---------------------------------------------------------------------------
# fetch_github_readme
# ---------------------------------------------------------------------------


def _stub_fetch_text(monkeypatch, fake):
    """Replace the network call site with a canned response factory."""
    monkeypatch.setattr(tools, "_fetch_text", fake)


def test_fetch_github_readme_success(monkeypatch):
    captured: dict = {}

    def fake_fetch(url, *, timeout, max_bytes):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["max_bytes"] = max_bytes
        return {
            "status": 200,
            "content_type": "text/plain; charset=utf-8",
            "body": "# openai-python\n\nThe official OpenAI Python library.\n",
        }

    _stub_fetch_text(monkeypatch, fake_fetch)
    result = tools.fetch_github_readme("https://github.com/openai/openai-python")

    assert result["ok"] is True
    assert result["owner"] == "openai"
    assert result["repo"] == "openai-python"
    assert "openai-python" in result["readme"]
    # We always fetch the HEAD pseudo-ref so GitHub resolves the
    # default branch — main vs master shouldn't matter.
    assert captured["url"] == (
        "https://raw.githubusercontent.com/openai/openai-python/HEAD/README.md"
    )
    assert captured["timeout"] == tools._README_TIMEOUT_SECONDS
    assert captured["max_bytes"] == tools._README_MAX_BYTES


def test_fetch_github_readme_rejects_non_github_url(monkeypatch):
    # The fetch path must not be hit at all when validation fails.
    def fail_if_called(*_args, **_kwargs):  # pragma: no cover - guard
        raise AssertionError("_fetch_text should not be called for an invalid URL")

    _stub_fetch_text(monkeypatch, fail_if_called)
    result = tools.fetch_github_readme("https://google.com/openai/openai-python")
    assert result["ok"] is False
    assert result["error"] == "invalid_url"
    # Loose check on the user-facing message — it should hint the user
    # to provide a github.com URL or describe the project directly.
    assert "github.com" in result["message"]


def test_fetch_github_readme_handles_timeout(monkeypatch):
    def fake_fetch(url, *, timeout, max_bytes):
        return {"error": "timeout", "details": f"Fetch exceeded {timeout:.0f}s."}

    _stub_fetch_text(monkeypatch, fake_fetch)
    result = tools.fetch_github_readme("https://github.com/openai/openai-python")
    assert result["ok"] is False
    assert result["error"] == "timeout"
    # The user-facing fallback message routes the model toward asking
    # the user directly instead of inventing a description.
    assert "share the project" in result["message"]


def test_fetch_github_readme_handles_oversize(monkeypatch):
    def fake_fetch(url, *, timeout, max_bytes):
        return {"error": "oversize", "details": f"README exceeds {max_bytes} bytes."}

    _stub_fetch_text(monkeypatch, fake_fetch)
    result = tools.fetch_github_readme("https://github.com/openai/openai-python")
    assert result["ok"] is False
    assert result["error"] == "oversize"


def test_fetch_github_readme_handles_wrong_content_type(monkeypatch):
    def fake_fetch(url, *, timeout, max_bytes):
        return {
            "error": "wrong_content_type",
            "details": "Expected text/markdown or text/plain, got application/octet-stream.",
        }

    _stub_fetch_text(monkeypatch, fake_fetch)
    result = tools.fetch_github_readme("https://github.com/foo/bar")
    assert result["ok"] is False
    assert result["error"] == "wrong_content_type"


def test_fetch_github_readme_handles_http_404(monkeypatch):
    def fake_fetch(url, *, timeout, max_bytes):
        return {"error": "http_status", "details": f"HTTP 404 from {url}."}

    _stub_fetch_text(monkeypatch, fake_fetch)
    result = tools.fetch_github_readme(
        "https://github.com/this-user-does-not/exist-anywhere"
    )
    assert result["ok"] is False
    assert result["error"] == "http_status"


# ---------------------------------------------------------------------------
# execute_tool (dispatcher)
# ---------------------------------------------------------------------------


def test_execute_tool_dispatches_to_fetch_github_readme(monkeypatch):
    _stub_fetch_text(
        monkeypatch,
        lambda url, *, timeout, max_bytes: {
            "status": 200,
            "content_type": "text/plain",
            "body": "# hello\n",
        },
    )
    output = tools.execute_tool(
        "fetch_github_readme",
        json.dumps({"url": "https://github.com/openai/openai-python"}),
    )
    payload = json.loads(output)
    assert payload["ok"] is True
    assert payload["repo"] == "openai-python"


def test_execute_tool_rejects_unknown_tool():
    output = tools.execute_tool("definitely_not_a_tool", "{}")
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"] == "unknown_tool"


def test_execute_tool_rejects_invalid_arguments_json():
    output = tools.execute_tool("fetch_github_readme", "{not json")
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_arguments"


def test_execute_tool_rejects_non_object_arguments():
    # Valid JSON, but not an object — must not blow up.
    output = tools.execute_tool("fetch_github_readme", json.dumps(["not", "an", "object"]))
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_arguments"


def test_execute_tool_rejects_wrong_argument_shape():
    # Object, but wrong keys → TypeError on the impl call → reported
    # back to the model as a tool error, not raised.
    output = tools.execute_tool(
        "fetch_github_readme", json.dumps({"unexpected_key": "x"})
    )
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"] == "invalid_arguments"


# ---------------------------------------------------------------------------
# Tool spec sanity checks
# ---------------------------------------------------------------------------


def test_tool_spec_includes_fetch_github_readme():
    names = [spec["name"] for spec in tools.RESUME_BUILDER_TOOL_SPECS]
    assert "fetch_github_readme" in names


def test_tool_spec_has_required_parameters_schema():
    spec = tools.FETCH_GITHUB_README_TOOL_SPEC
    assert spec["type"] == "function"
    params = spec["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["url"]
    assert "url" in params["properties"]
    # additionalProperties must be False so the LLM can't smuggle extra
    # fields into the call.
    assert params["additionalProperties"] is False
