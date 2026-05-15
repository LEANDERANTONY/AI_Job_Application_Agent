"""Static audit of user-facing error messages.

Two checks:

1. **Backend HTTPException details.** Every `raise HTTPException(detail=...)`
   call across `backend/routers/` and `src/` must use a friendly source —
   either a string literal or `<error>.user_message` from an `AppError`
   subclass. Raw `str(error)` is allowed only when the surrounding `except`
   clause catches `AppError` (so the user_message is what `str()` returns
   anyway). Anything else is a candidate for leaking Python exception text
   to the user and gets flagged.

2. **Frontend error rendering.** Every `error instanceof Error ? error.message`
   construct in component / hook code must be paired with a
   `humanizeApiError` call on the same statement. The legacy raw-message
   pattern shows users things like `Request failed with status 503` or
   Pydantic-array text. Substring-comparison reads like
   `error.message.toLowerCase()` for `.includes("not found")` are
   allowlisted because they're not rendered.

The test runs against the source tree (no imports), so it stays fast and
catches regressions at PR time.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterable

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent

BACKEND_DIRS = [
    REPO_ROOT / "backend" / "routers",
    REPO_ROOT / "backend" / "services",
    REPO_ROOT / "src",
]

FRONTEND_DIR = REPO_ROOT / "frontend" / "src"


# ---------------------------------------------------------------------------
# Backend audit
# ---------------------------------------------------------------------------


def _iter_python_files(roots: Iterable[Path]):
    for root in roots:
        if not root.is_dir():
            continue
        yield from sorted(root.rglob("*.py"))


def _find_enclosing_try(node: ast.AST, ancestors: list[ast.AST]) -> ast.Try | None:
    """Return the nearest enclosing `try` statement, or None."""
    for ancestor in reversed(ancestors):
        if isinstance(ancestor, ast.Try):
            return ancestor
    return None


def _except_handler_for(try_node: ast.Try, raise_node: ast.Raise) -> ast.ExceptHandler | None:
    """Find which except handler contains a given raise node."""
    for handler in try_node.handlers:
        for child in ast.walk(handler):
            if child is raise_node:
                return handler
    return None


def _exception_class_names(handler: ast.ExceptHandler) -> set[str]:
    """Return the simple class names caught by an except handler."""
    if handler.type is None:
        return {"Exception"}  # bare except
    captured: set[str] = set()
    for node in ast.walk(handler.type):
        if isinstance(node, ast.Name):
            captured.add(node.id)
        elif isinstance(node, ast.Attribute):
            captured.add(node.attr)
    return captured


def _detail_kwarg(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "detail":
            return kw.value
    return None


def _is_user_message_attr(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "user_message"


def _is_string_constant(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    # f-strings get classified as friendly because the developer
    # constructed the string explicitly.
    if isinstance(node, ast.JoinedStr):
        return True
    return False


def _is_str_call_on_error(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Name) or node.func.id != "str":
        return False
    if not node.args:
        return False
    arg = node.args[0]
    return isinstance(arg, ast.Name)


# Names of error classes that are friendly by contract — their str()
# returns the user_message because the codebase raises them with
# hand-written user-facing strings.
_FRIENDLY_ERROR_CLASSES = {
    "AppError",
    "InputValidationError",
    "AgentExecutionError",
    "ExportError",
    # Pydantic validators + service-layer ValueErrors are raised with
    # hand-written user-facing strings; if someone raises a raw
    # ValueError from deep code, that would still leak — but it's a
    # much smaller surface than catching generic Exception.
    "ValueError",
    # The workspace persistence + saved-jobs services follow a
    # convention of raising `RuntimeError("<user-facing copy>")` for
    # configuration / state preconditions (e.g. "Saved workspace
    # persistence is not configured."). Adding it here matches that
    # convention. The trade-off: a stray RuntimeError raised from
    # deeper code with a non-friendly message would leak. The
    # synthetic error-handling runner catches that drift at runtime.
    "RuntimeError",
}


def _classify_detail(call: ast.Call, ancestors: list[ast.AST], raise_node: ast.Raise) -> str:
    detail = _detail_kwarg(call)
    if detail is None:
        return "safe"  # no detail kwarg — FastAPI uses default
    if _is_string_constant(detail):
        return "safe"
    if _is_user_message_attr(detail):
        return "safe"
    if _is_str_call_on_error(detail):
        try_node = _find_enclosing_try(detail, ancestors)
        if try_node is None:
            return "leaky"
        handler = _except_handler_for(try_node, raise_node)
        if handler is None:
            return "leaky"
        caught = _exception_class_names(handler)
        if caught & _FRIENDLY_ERROR_CLASSES and "Exception" not in caught:
            return "safe"
        return "leaky"
    # Unknown detail expression — flag for review.
    return "review"


def _walk_with_ancestors(tree: ast.AST):
    """Yield (node, ancestors) pairs for every node in the tree."""
    stack: list[tuple[ast.AST, list[ast.AST]]] = [(tree, [])]
    while stack:
        node, ancestors = stack.pop()
        yield node, ancestors
        children_ancestors = ancestors + [node]
        for child in ast.iter_child_nodes(node):
            stack.append((child, children_ancestors))


def _audit_python_file(path: Path) -> list[dict]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    findings: list[dict] = []
    for node, ancestors in _walk_with_ancestors(tree):
        if not isinstance(node, ast.Raise):
            continue
        if not isinstance(node.exc, ast.Call):
            continue
        call = node.exc
        if not isinstance(call.func, ast.Name) or call.func.id != "HTTPException":
            continue
        verdict = _classify_detail(call, ancestors, node)
        if verdict == "safe":
            continue
        findings.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "line": node.lineno,
                "verdict": verdict,
                "detail_src": ast.unparse(_detail_kwarg(call)) if _detail_kwarg(call) else "<missing>",
            }
        )
    return findings


# Curated allowlist of HTTPException sites that intentionally pass a
# raw str(...) or non-literal detail because the surrounding service
# raises with a hand-written user-facing string. Each entry is
# (relative_path, line_number).
#
# Note: path uses os.sep, matching what `Path.relative_to(REPO_ROOT)`
# returns on the current platform. On Windows that's backslash.
import os as _os_for_paths

_BACKEND_ALLOWLIST: set[tuple[str, int]] = {
    # backend/routers/workspace.py — InvalidFeedbackError is raised in
    # backend/services/feedback_service.py with three hand-written
    # user-safe messages ("Unsupported feedback surface: ...",
    # "Rating must be 'up' or 'down', got ...", "user_id is required
    # to record feedback."). Surfacing them directly helps the client
    # debug a bad payload; there's no internal state in the string.
    # Line moved from 617 to 629 when the AuthRequiredError handler
    # for /workspace/transcribe was added above it.
    (_os_for_paths.path.join("backend", "routers", "workspace.py"), 629),
}


def test_backend_http_exceptions_use_friendly_detail():
    findings: list[dict] = []
    for path in _iter_python_files(BACKEND_DIRS):
        findings.extend(_audit_python_file(path))

    unexpected = [
        finding
        for finding in findings
        if (finding["path"], finding["line"]) not in _BACKEND_ALLOWLIST
    ]

    if unexpected:
        report = "\n".join(
            f"  {f['path']}:{f['line']} [{f['verdict']}] detail={f['detail_src']}"
            for f in unexpected
        )
        pytest.fail(
            "HTTPException sites with potentially leaky `detail` arguments. "
            "Use a string literal, `error.user_message`, or wrap in an "
            "`except AppError` clause. Allowlist a site only after manual "
            "review:\n" + report
        )


# ---------------------------------------------------------------------------
# Frontend audit
# ---------------------------------------------------------------------------


_FRONTEND_FILE_GLOBS = ("**/*.ts", "**/*.tsx")

# Regex matches the legacy pattern: `error instanceof Error\n? error.message\n: ...`
# Spread across 1-3 lines so we catch single-line and multi-line forms.
_LEGACY_ERROR_MESSAGE_RE = re.compile(
    r"error\s+instanceof\s+Error\s*\??\s*\n?\s*\?\s*error\.message",
    re.MULTILINE,
)

# Allowlisted reads: substring comparisons that don't render to the user.
_ALLOWLISTED_READ_PATTERNS = (
    re.compile(r"error\.message\.toLowerCase\(\)"),
    re.compile(r"error\.message\.includes\("),
)


def _iter_frontend_files() -> list[Path]:
    if not FRONTEND_DIR.is_dir():
        return []
    files: list[Path] = []
    for pattern in _FRONTEND_FILE_GLOBS:
        files.extend(FRONTEND_DIR.rglob(pattern))
    # Skip the humanizer itself + its tests + node_modules.
    return sorted(
        p
        for p in files
        if "node_modules" not in p.parts
        and p.name != "humanizeApiError.ts"
        and not p.name.endswith(".d.ts")
    )


def _strip_allowlisted_reads(source: str) -> str:
    cleaned = source
    for pattern in _ALLOWLISTED_READ_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned


def _audit_frontend_file(path: Path) -> list[dict]:
    source = path.read_text(encoding="utf-8")
    cleaned = _strip_allowlisted_reads(source)

    findings: list[dict] = []
    for match in _LEGACY_ERROR_MESSAGE_RE.finditer(cleaned):
        line = cleaned[: match.start()].count("\n") + 1
        findings.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "line": line,
                "match": match.group(0).strip().replace("\n", " ")[:120],
            }
        )
    return findings


def test_frontend_error_renders_route_through_humanizer():
    """Components and hooks should render error messages via
    `humanizeApiError(...)` rather than raw `error.message`. Catches
    drift when a new handler is added with the legacy pattern."""
    findings: list[dict] = []
    for path in _iter_frontend_files():
        findings.extend(_audit_frontend_file(path))

    if findings:
        report = "\n".join(
            f"  {f['path']}:{f['line']}    {f['match']}"
            for f in findings
        )
        pytest.fail(
            "Found `error instanceof Error ? error.message : ...` patterns "
            "that should route through `humanizeApiError(error, fallback)` "
            "instead. Substring-comparison reads (e.g. "
            "`error.message.toLowerCase()` for `.includes('not found')`) "
            "are allowlisted automatically:\n" + report
        )
