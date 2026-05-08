"""Smoke tests for the application-level retry layer in OpenAIService.

These don't hit the real OpenAI API. They construct an
``OpenAIService`` with a mocked ``responses.create`` that raises a
specific exception, and verify the helper:

  - retries once on a retryable exception (APIConnectionError /
    APITimeoutError / InternalServerError)
  - does NOT retry on a non-retryable exception
    (BadRequestError / AuthenticationError)
  - returns the success response if the second attempt succeeds
  - raises after the second attempt if both fail

Keeps the retry contract pinned so future SDK upgrades or refactors
don't silently turn into "retries on everything" or "retries on
nothing".
"""

import time
from unittest.mock import MagicMock

import pytest

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
)

from src.openai_service import OpenAIService


def _make_service(create_side_effects):
    """Build an OpenAIService with a mocked client whose
    ``responses.create`` returns / raises according to the supplied
    list of side effects (one per call attempt)."""
    service = OpenAIService(api_key="sk-test-fake", model="gpt-test")
    mock_client = MagicMock()
    mock_client.responses.create = MagicMock(side_effect=create_side_effects)
    service._client = mock_client
    return service, mock_client


def _make_api_connection_error():
    # APIConnectionError requires a `request` argument in newer SDK
    # versions; passing a MagicMock avoids constructor failures.
    return APIConnectionError(request=MagicMock())


def _make_api_timeout_error():
    return APITimeoutError(request=MagicMock())


def _make_internal_server_error():
    # 500 errors take a message and a response/body. MagicMock
    # satisfies the SDK's __init__ requirements.
    response = MagicMock()
    response.status_code = 500
    return InternalServerError(
        message="upstream broke",
        response=response,
        body=None,
    )


def _make_bad_request_error():
    response = MagicMock()
    response.status_code = 400
    return BadRequestError(
        message="bad payload",
        response=response,
        body=None,
    )


def _make_auth_error():
    response = MagicMock()
    response.status_code = 401
    return AuthenticationError(
        message="bad api key",
        response=response,
        body=None,
    )


# ─── retryable cases — should retry once ─────────────────────────────


@pytest.mark.parametrize(
    "make_exc",
    [
        _make_api_connection_error,
        _make_api_timeout_error,
        _make_internal_server_error,
    ],
)
def test_app_retry_retries_once_on_retryable_then_succeeds(make_exc):
    """A retryable exception on attempt 1 → app retries → attempt 2
    succeeds → helper returns the success response."""
    success_response = MagicMock(name="success-response")
    service, client = _make_service([make_exc(), success_response])

    result = service._create_response_with_app_retry(
        request_payload={"model": "gpt-test"},
        task_name="unit-test",
        resolved_model="gpt-test",
        started_at=time.perf_counter(),
    )

    assert result is success_response
    assert client.responses.create.call_count == 2


@pytest.mark.parametrize(
    "make_exc",
    [
        _make_api_connection_error,
        _make_api_timeout_error,
        _make_internal_server_error,
    ],
)
def test_app_retry_raises_after_two_failed_retryable_attempts(make_exc):
    """Both attempts raise retryable exceptions → helper re-raises
    the second exception. We don't add a third attempt."""
    first_exc = make_exc()
    second_exc = make_exc()
    service, client = _make_service([first_exc, second_exc])

    with pytest.raises(type(second_exc)) as excinfo:
        service._create_response_with_app_retry(
            request_payload={"model": "gpt-test"},
            task_name="unit-test",
            resolved_model="gpt-test",
            started_at=time.perf_counter(),
        )

    assert excinfo.value is second_exc
    assert client.responses.create.call_count == 2


# ─── non-retryable cases — should NOT retry ──────────────────────────


@pytest.mark.parametrize(
    "make_exc",
    [_make_bad_request_error, _make_auth_error],
)
def test_app_retry_does_not_retry_on_non_retryable(make_exc):
    """4xx-class errors (bad request, auth) are deterministic — a
    retry won't help and would just add latency. Helper must raise
    on the FIRST attempt without calling create again."""
    exc = make_exc()
    service, client = _make_service([exc])

    with pytest.raises(type(exc)) as excinfo:
        service._create_response_with_app_retry(
            request_payload={"model": "gpt-test"},
            task_name="unit-test",
            resolved_model="gpt-test",
            started_at=time.perf_counter(),
        )

    assert excinfo.value is exc
    assert client.responses.create.call_count == 1


# ─── happy path — single attempt succeeds ────────────────────────────


def test_app_retry_returns_immediately_on_first_success():
    """No exception → helper returns on the first attempt with no
    retry. Verifies we don't pay the retry cost on the happy path."""
    success_response = MagicMock(name="success-response")
    service, client = _make_service([success_response])

    result = service._create_response_with_app_retry(
        request_payload={"model": "gpt-test"},
        task_name="unit-test",
        resolved_model="gpt-test",
        started_at=time.perf_counter(),
    )

    assert result is success_response
    assert client.responses.create.call_count == 1
