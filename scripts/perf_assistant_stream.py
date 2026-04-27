"""Latency smoke test for the streaming assistant endpoint.

Hits ``POST /api/workspace/assistant/answer/stream`` and prints
wall-clock timings for the events that matter for perceived snappiness:

  - request sent             -> 0.0 ms
  - first byte received      -> TTFB
  - first ``meta`` event     -> when the source-chip row could render
  - first ``delta`` event    -> when the first answer text could paint
  - last ``delta`` event     -> when the answer stops growing
  - ``done`` event           -> total wall-clock time

This is intentionally a stdlib-only script (``http.client``) so it
runs anywhere ``python`` runs and doesn't pull in extra deps. It also
sets ``Accept: text/event-stream`` and disables HTTP/1.1 keep-alive
quirks via ``Connection: close`` so the read loop terminates cleanly.

Use it to:

  1. Verify locally that the streaming wire works against your dev
     uvicorn (no auth, deterministic fallback path).
  2. Verify against the deployed Caddy path that ``flush_interval -1``
     and ``X-Accel-Buffering: no`` actually flush per-frame and
     nothing is buffering on the way down.
  3. Compare time-to-first-delta with and without ``--token`` (i.e.
     deterministic-fallback vs OpenAI-backed).

Examples
--------
Local, deterministic fallback (no OpenAI key needed)::

    uv run python scripts/perf_assistant_stream.py \\
        --url http://localhost:8000/api/workspace/assistant/answer/stream

Local, OpenAI-backed (real model, real first-token latency)::

    uv run python scripts/perf_assistant_stream.py \\
        --url http://localhost:8000/api/workspace/assistant/answer/stream \\
        --token "$YOUR_SUPABASE_ACCESS_TOKEN" \\
        --refresh-token "$YOUR_SUPABASE_REFRESH_TOKEN"

Deployed::

    uv run python scripts/perf_assistant_stream.py \\
        --url https://api.example.com/api/workspace/assistant/answer/stream \\
        --token "$ACCESS" --refresh-token "$REFRESH"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.client import HTTPConnection, HTTPSConnection
from typing import Iterator
from urllib.parse import urlparse


DEFAULT_URL = "http://localhost:8000/api/workspace/assistant/answer/stream"
DEFAULT_QUESTION = "What can I do on this page?"
DEFAULT_CURRENT_PAGE = "Workspace"


def _build_request_body(question: str, current_page: str) -> bytes:
    payload = {
        "question": question,
        "current_page": current_page,
        "workspace_snapshot": None,
        "history": [],
    }
    return json.dumps(payload).encode("utf-8")


def _open_connection(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise SystemExit(f"Unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if host is None:
        raise SystemExit(f"URL is missing a hostname: {url!r}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if parsed.scheme == "https":
        return HTTPSConnection(host, port, timeout=120), parsed.path or "/"
    return HTTPConnection(host, port, timeout=120), parsed.path or "/"


def _iter_sse_frames(response) -> Iterator[tuple[str, dict]]:
    """Yield ``(event_name, data)`` tuples as frames arrive.

    Reads the response one chunk at a time and splits on the
    blank-line frame delimiter (``\\n\\n``). Partial frames are kept
    in a buffer until the next chunk arrives, so a single TCP read
    that contains multiple frames yields them all immediately.
    """
    buffer = ""
    while True:
        chunk = response.read(1)  # single-byte reads — coarse but
                                  # robust to chunk sizing on every
                                  # backend we care about.
        if not chunk:
            break
        try:
            buffer += chunk.decode("utf-8")
        except UnicodeDecodeError:
            # Multi-byte UTF-8 boundary — re-attempt on next loop.
            continue

        delimiter_index = buffer.find("\n\n")
        while delimiter_index >= 0:
            frame = buffer[:delimiter_index]
            buffer = buffer[delimiter_index + 2:]
            event_name, data = _parse_frame(frame)
            yield event_name, data
            delimiter_index = buffer.find("\n\n")


def _parse_frame(frame: str) -> tuple[str, dict]:
    event_name = ""
    data_lines: list[str] = []
    for line in frame.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
    data_text = "\n".join(data_lines)
    if not data_text:
        return event_name, {}
    try:
        return event_name, json.loads(data_text)
    except json.JSONDecodeError:
        return event_name, {"_raw": data_text}


def _format_ms(start: float, marker: float | None) -> str:
    if marker is None:
        return "    n/a"
    return f"{(marker - start) * 1000:7.1f} ms"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--url", default=DEFAULT_URL, help="Full URL of the streaming endpoint.")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="Question text to send.")
    parser.add_argument("--current-page", default=DEFAULT_CURRENT_PAGE, help="`current_page` field.")
    parser.add_argument("--token", default="", help="Supabase access token. Optional.")
    parser.add_argument("--refresh-token", default="", help="Supabase refresh token. Optional.")
    parser.add_argument(
        "--print-text",
        action="store_true",
        help="Print the assembled answer text after the stream completes.",
    )
    args = parser.parse_args()

    body = _build_request_body(args.question, args.current_page)
    connection, request_path = _open_connection(args.url)

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Connection": "close",
        "Content-Length": str(len(body)),
    }
    if args.token:
        headers["X-Auth-Access-Token"] = args.token
    if args.refresh_token:
        headers["X-Auth-Refresh-Token"] = args.refresh_token

    print(f"POST {args.url}")
    print(f"  question      : {args.question!r}")
    print(f"  current_page  : {args.current_page!r}")
    print(f"  authenticated : {bool(args.token)}")
    print()

    t_start = time.monotonic()
    connection.request("POST", request_path, body=body, headers=headers)
    response = connection.getresponse()
    t_first_byte = time.monotonic()

    if response.status != 200:
        body_text = response.read().decode("utf-8", errors="replace")
        print(f"!! Non-200 response: {response.status} {response.reason}")
        print(body_text)
        return 1

    content_type = response.getheader("Content-Type", "")
    if "text/event-stream" not in content_type:
        print(f"!! Unexpected Content-Type: {content_type!r}")
        return 1

    t_meta: float | None = None
    t_first_delta: float | None = None
    t_last_delta: float | None = None
    t_done: float | None = None
    delta_count = 0
    delta_chars = 0
    delta_inter_arrival_ms: list[float] = []
    sources: list[str] = []
    error_detail: str | None = None
    answer_chunks: list[str] = []

    for event_name, data in _iter_sse_frames(response):
        now = time.monotonic()
        if event_name == "meta" and t_meta is None:
            t_meta = now
            sources = list(data.get("sources") or [])
        elif event_name == "delta":
            if t_first_delta is None:
                t_first_delta = now
            else:
                delta_inter_arrival_ms.append((now - (t_last_delta or now)) * 1000)
            t_last_delta = now
            text = data.get("text", "")
            delta_count += 1
            delta_chars += len(text)
            if args.print_text:
                answer_chunks.append(text)
        elif event_name == "error":
            error_detail = str(data.get("detail") or "(no detail)")
        elif event_name == "done":
            t_done = now
            break

    if t_done is None:
        # Stream ended without a `done` event — record the wall-clock
        # so the summary still has a useful endpoint.
        t_done = time.monotonic()

    print("Timings (ms from request-sent):")
    print(f"  first byte (HTTP) : {_format_ms(t_start, t_first_byte)}")
    print(f"  meta event        : {_format_ms(t_start, t_meta)}")
    print(f"  first delta       : {_format_ms(t_start, t_first_delta)}")
    print(f"  last  delta       : {_format_ms(t_start, t_last_delta)}")
    print(f"  done              : {_format_ms(t_start, t_done)}")
    print()
    print("Stream summary:")
    print(f"  delta events     : {delta_count}")
    print(f"  delta chars      : {delta_chars}")
    if delta_inter_arrival_ms:
        avg = sum(delta_inter_arrival_ms) / len(delta_inter_arrival_ms)
        print(f"  avg inter-delta  : {avg:.1f} ms")
        print(
            f"  inter-delta range: {min(delta_inter_arrival_ms):.1f} ms"
            f" – {max(delta_inter_arrival_ms):.1f} ms"
        )
    print(f"  sources          : {sources}")
    if error_detail:
        print(f"  error            : {error_detail}")

    if args.print_text:
        print()
        print("Assembled answer:")
        print("-" * 60)
        print("".join(answer_chunks).strip())
        print("-" * 60)

    # Exit non-zero on error or missing milestones so this can wire
    # into a deploy smoke check.
    if error_detail:
        return 2
    if t_meta is None or t_first_delta is None:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
