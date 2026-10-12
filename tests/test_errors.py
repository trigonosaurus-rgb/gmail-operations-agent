"""Vendor exceptions map onto retry / dead-letter / pause the same way everywhere."""

import json

import httpx
import openai
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from httplib2 import Response
from notion_client.errors import APIResponseError

from gmail_operations_agent.errors import BlockedError, PermanentError, TransientError
from gmail_operations_agent.integrations.google_api import classify_google_error
from gmail_operations_agent.integrations.notion import _classify as classify_notion
from gmail_operations_agent.llm.openai_provider import classify_openai_error


def http_error(status: int, reason: str = "") -> HttpError:
    content = json.dumps({"error": {"message": "msg", "errors": [{"reason": reason}]}})
    return HttpError(Response({"status": status}), content.encode())


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (http_error(429), TransientError),
        (http_error(503), TransientError),
        (http_error(403, "userRateLimitExceeded"), TransientError),
        (http_error(403, "insufficientPermissions"), BlockedError),
        (http_error(401), BlockedError),
        (http_error(400), PermanentError),
        (http_error(404), PermanentError),
        (RefreshError("invalid_grant"), BlockedError),
        (TimeoutError(), TransientError),
        (ConnectionResetError(), TransientError),
    ],
)
def test_google_errors(exc: Exception, expected: type) -> None:
    assert isinstance(classify_google_error(exc), expected)


def test_unknown_google_exception_is_not_swallowed() -> None:
    assert classify_google_error(ValueError("bug")) is None


def openai_status_error(cls: type[openai.APIStatusError], status: int, code: str | None = None):  # type: ignore[no-untyped-def]
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status, request=request, json={"error": {"code": code}})
    return cls("error", response=response, body={"code": code} if code else None)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (openai_status_error(openai.RateLimitError, 429), TransientError),
        (openai_status_error(openai.RateLimitError, 429, "insufficient_quota"), BlockedError),
        (openai_status_error(openai.AuthenticationError, 401), BlockedError),
        (openai_status_error(openai.NotFoundError, 404), BlockedError),
        (openai_status_error(openai.InternalServerError, 500), TransientError),
        (openai_status_error(openai.BadRequestError, 400), PermanentError),
        (openai.APITimeoutError(httpx.Request("POST", "https://x")), TransientError),
    ],
)
def test_openai_errors(exc: openai.OpenAIError, expected: type) -> None:
    assert isinstance(classify_openai_error(exc, "gpt-6-luna"), expected)


def notion_error(status: int, code: str) -> APIResponseError:
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.notion.com"))
    return APIResponseError(
        code=code, status=status, message="m", headers=response.headers, raw_body_text=""
    )


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (429, "rate_limited", TransientError),
        (502, "bad_gateway", TransientError),
        (401, "unauthorized", BlockedError),
        (404, "object_not_found", BlockedError),
        (400, "validation_error", PermanentError),
    ],
)
def test_notion_errors(status: int, code: str, expected: type) -> None:
    assert isinstance(classify_notion(notion_error(status, code)), expected)
