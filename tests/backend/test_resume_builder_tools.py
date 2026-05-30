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
from src.openai_service import OpenAIService


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
# _fetch_text — redirect hardening (review L2). These exercise the REAL
# network call site (requests.get stubbed) rather than the _fetch_text stub
# the tests above use, so they lock in the allow_redirects=False contract.
# ---------------------------------------------------------------------------


class _FakeRaw:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, n, decode_content=True):
        return self._body[:n]


class _FakeResponse:
    def __init__(self, status_code, content_type, body=b""):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.raw = _FakeRaw(body)

    def close(self):
        pass


def test_fetch_text_disables_redirects(monkeypatch):
    """The GitHub raw fetch must NOT follow redirects — the host is validated
    up front, but a followed redirect chain wouldn't be re-checked per hop."""
    captured: dict = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(200, "text/plain; charset=utf-8", b"# hi\n")

    monkeypatch.setattr(tools.requests, "get", fake_get)
    result = tools._fetch_text(
        "https://raw.githubusercontent.com/openai/openai-python/HEAD/README.md",
        timeout=5.0,
        max_bytes=1000,
    )
    assert result["status"] == 200
    assert captured["allow_redirects"] is False


def test_fetch_text_rejects_redirect_status(monkeypatch):
    """A 3xx (a would-be redirect) lands as http_status, never a followed hop."""

    def fake_get(url, **kwargs):
        return _FakeResponse(302, "text/html", b"")

    monkeypatch.setattr(tools.requests, "get", fake_get)
    result = tools._fetch_text(
        "https://raw.githubusercontent.com/openai/openai-python/HEAD/README.md",
        timeout=5.0,
        max_bytes=1000,
    )
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
    # Function tools have a "name" key at the top level. Server-side
    # built-in tools (like OpenAI's web_search) don't — they only
    # have "type". Filter to function tools before reading names.
    names = [
        spec["name"]
        for spec in tools.RESUME_BUILDER_TOOL_SPECS
        if spec.get("type") == "function"
    ]
    assert "fetch_github_readme" in names


def test_tool_spec_includes_web_search():
    """Slice 1F: ``web_search`` is exposed as a FUNCTION tool (not a
    server-side ``{"type": "web_search"}`` spec) because OpenAI's
    server-side web_search is incompatible with JSON mode
    (``text.format = json_object``) that our intake contract
    requires — the API returns "Web Search cannot be used with JSON
    mode." The function wrap lets the dispatcher make a separate
    inner ``responses.create`` call without JSON mode for the search
    itself, returning the synthesized text back to the agent."""
    function_tool_names = [
        spec["name"]
        for spec in tools.RESUME_BUILDER_TOOL_SPECS
        if spec.get("type") == "function"
    ]
    assert "web_search" in function_tool_names
    # And confirm the spec has a required `query` parameter.
    web_search_spec = next(
        spec
        for spec in tools.RESUME_BUILDER_TOOL_SPECS
        if spec.get("name") == "web_search"
    )
    assert web_search_spec["parameters"]["required"] == ["query"]
    assert "query" in web_search_spec["parameters"]["properties"]
    assert web_search_spec["parameters"]["additionalProperties"] is False


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


# ---------------------------------------------------------------------------
# web_search dispatcher tests (hermetic — mocks the OpenAI client)
# ---------------------------------------------------------------------------


class _StubOpenAIClient:
    """Minimal client mock that records the call args and returns a
    canned response shape. Matches the duck-typing OpenAIService gives
    us — ``client.responses.create(...)``."""

    def __init__(self, *, output_text="External context summary.", raise_exc=None):
        self._output_text = output_text
        self._raise = raise_exc
        self.last_payload = None
        # Records the kwargs passed to with_options (review L4) — the web-search
        # timeout is applied via client.with_options(timeout=...). The real
        # client returns a configured copy; returning self keeps last_payload
        # observable on the same object.
        self.with_options_kwargs = None

        class _ResponsesNamespace:
            def __init__(_self, outer):
                _self._outer = outer

            def create(_self, **payload):
                _self._outer.last_payload = payload
                if _self._outer._raise is not None:
                    raise _self._outer._raise
                # Build a response object matching the SDK shape.
                class _Part:
                    type = "output_text"
                    text = _self._outer._output_text

                class _Message:
                    type = "message"
                    content = [_Part()]

                class _Response:
                    output = [_Message()]

                return _Response()

        self.responses = _ResponsesNamespace(self)

    def with_options(self, **kwargs):
        self.with_options_kwargs = kwargs
        return self


def _make_stub_service(*, output_text="External context summary.", raise_exc=None):
    """A REAL OpenAIService wrapping the stub client, so the web_search
    dispatcher exercises the ACCOUNTED ``run_builtin_web_search`` path —
    the raw-._client bypass it used to take is gone (review LLM-1)."""
    return OpenAIService(
        client=_StubOpenAIClient(output_text=output_text, raise_exc=raise_exc)
    )


def test_web_search_success_returns_synthesized_text():
    svc = _make_stub_service(
        output_text="Anthropic Senior MLE roles typically expect: 1) ..."
    )
    output = tools.execute_tool(
        "web_search",
        json.dumps({"query": "Anthropic Senior MLE expectations"}),
        openai_service=svc,
    )
    payload = json.loads(output)
    assert payload["ok"] is True
    assert "Anthropic" in payload["result"]
    # The inner call must NOT use json_object format (that's the whole
    # reason for the function wrap) and must enable the built-in
    # web_search server-side tool.
    sent_payload = svc._client.last_payload
    assert "text" not in sent_payload or sent_payload.get("text", {}).get(
        "format", {}
    ).get("type") != "json_object"
    assert any(
        t.get("type") == "web_search" for t in sent_payload.get("tools", [])
    )


def test_web_search_dispatcher_routes_through_accounting():
    """The dispatcher now goes through OpenAIService.run_builtin_web_search,
    so the search records a cost-trace (and meters tokens). Before the
    fix it reached the raw ._client and recorded nothing (LLM-1)."""
    captured: list[dict] = []
    service = OpenAIService(
        client=_StubOpenAIClient(output_text="Anthropic Senior MLE roles ..."),
        user_id="user-ws",
        cost_trace_recorder=captured.append,
    )
    output = tools.execute_tool(
        "web_search",
        json.dumps({"query": "Anthropic Senior MLE expectations"}),
        openai_service=service,
    )
    payload = json.loads(output)
    assert payload["ok"] is True
    assert len(captured) == 1
    assert captured[0]["task_name"] == "web_search"
    assert captured[0]["user_id"] == "user-ws"


def test_web_search_rejects_empty_query():
    svc = _make_stub_service()
    output = tools.execute_tool(
        "web_search", json.dumps({"query": "   "}), openai_service=svc
    )
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"] == "empty_query"


def test_web_search_requires_openai_service():
    # No openai_service forwarded — must return a structured error
    # rather than raising.
    output = tools.execute_tool(
        "web_search",
        json.dumps({"query": "Anthropic"}),
        openai_service=None,
    )
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"] == "no_openai_service"


def test_web_search_handles_dispatch_exception():
    svc = _make_stub_service(raise_exc=RuntimeError("API exploded"))
    output = tools.execute_tool(
        "web_search", json.dumps({"query": "test"}), openai_service=svc
    )
    payload = json.loads(output)
    assert payload["ok"] is False
    assert payload["error"] == "search_dispatch_failed"


def test_web_search_applies_its_own_timeout(monkeypatch):
    """L4 regression: the inner search call must run at WEB_SEARCH_TIMEOUT_SECONDS
    (30s), not the 120s client default — a slow search shouldn't stall an
    interactive intake turn for two minutes. The timeout reaches the client via
    client.with_options(timeout=...); assert that propagated end-to-end through
    _web_search -> run_builtin_web_search."""
    svc = _make_stub_service(output_text="Search synthesis.")
    output = tools.execute_tool(
        "web_search",
        json.dumps({"query": "Anthropic Senior MLE expectations"}),
        openai_service=svc,
    )
    assert json.loads(output)["ok"] is True
    assert svc._client.with_options_kwargs == {
        "timeout": tools.WEB_SEARCH_TIMEOUT_SECONDS
    }
    assert tools.WEB_SEARCH_TIMEOUT_SECONDS == 30.0


def test_web_search_truncates_oversize_result():
    huge = "x" * (tools.WEB_SEARCH_MAX_RESULT_CHARS + 5000)
    svc = _make_stub_service(output_text=huge)
    output = tools.execute_tool(
        "web_search", json.dumps({"query": "test"}), openai_service=svc
    )
    payload = json.loads(output)
    assert payload["ok"] is True
    assert len(payload["result"]) <= tools.WEB_SEARCH_MAX_RESULT_CHARS + 32
    assert payload["result"].endswith("…[truncated]")


def test_execute_tool_does_not_forward_openai_service_to_fetch():
    """fetch_github_readme is HTTP-only — execute_tool must NOT
    leak the openai_service into its kwargs (would crash since the
    impl doesn't accept it)."""
    def fake_fetch(url, *, timeout, max_bytes):
        return {"status": 200, "content_type": "text/plain", "body": "# Hi"}

    monkeypatch_target = tools._fetch_text
    tools._fetch_text = fake_fetch
    try:
        svc = _make_stub_service()
        output = tools.execute_tool(
            "fetch_github_readme",
            json.dumps({"url": "https://github.com/foo/bar"}),
            openai_service=svc,
        )
        payload = json.loads(output)
        assert payload["ok"] is True
    finally:
        tools._fetch_text = monkeypatch_target
