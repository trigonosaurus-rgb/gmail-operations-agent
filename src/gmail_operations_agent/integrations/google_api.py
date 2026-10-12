"""Non-blocking access to the Google API client.

googleapiclient is synchronous and built on httplib2, which is not thread-safe. Calls
run in worker threads via asyncio.to_thread, and every thread builds its own client
objects from the shared credentials.
"""

import asyncio
import json
import socket
import ssl
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

import google_auth_httplib2
import httplib2
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from gmail_operations_agent.errors import AgentError, BlockedError, PermanentError, TransientError

if TYPE_CHECKING:
    from googleapiclient._apis.gmail.v1 import GmailResource
    from googleapiclient._apis.sheets.v4 import SheetsResource

T = TypeVar("T")

# Retries inside one call for 429/5xx, with exponential backoff (googleapiclient built-in).
NUM_RETRIES = 3

_RETRYABLE_403 = {"rateLimitExceeded", "userRateLimitExceeded", "backendError"}


class GoogleApi:
    def __init__(self, creds: Credentials, timeout_seconds: float = 30) -> None:
        self._creds = creds
        self._timeout = timeout_seconds
        self._local = threading.local()

    def _http(self) -> google_auth_httplib2.AuthorizedHttp:
        return google_auth_httplib2.AuthorizedHttp(
            self._creds, http=httplib2.Http(timeout=self._timeout)
        )

    def gmail(self) -> "GmailResource":
        if not hasattr(self._local, "gmail"):
            self._local.gmail = build("gmail", "v1", http=self._http(), cache_discovery=False)
        service: GmailResource = self._local.gmail
        return service

    def sheets(self) -> "SheetsResource":
        if not hasattr(self._local, "sheets"):
            self._local.sheets = build("sheets", "v4", http=self._http(), cache_discovery=False)
        service: SheetsResource = self._local.sheets
        return service

    async def call(self, fn: Callable[[], T]) -> T:
        """Run a blocking client call in a thread and translate its errors."""
        try:
            return await asyncio.to_thread(fn)
        except AgentError:
            raise
        except Exception as exc:
            mapped = classify_google_error(exc)
            if mapped is None:
                raise
            raise mapped from exc


def classify_google_error(exc: BaseException) -> AgentError | None:
    """Map a Google client exception to the pipeline taxonomy; None means 'a bug'."""
    if isinstance(exc, HttpError):
        status = int(exc.resp.status)
        reason = _http_error_reason(exc)
        if status == 429 or status >= 500 or (status == 403 and reason in _RETRYABLE_403):
            return TransientError(f"Google API {status} {reason}".strip())
        if status == 401:
            return BlockedError("google", "credentials were rejected; run `gmail-agent auth`")
        if status == 403:
            return BlockedError("google", f"permission denied ({reason or 'forbidden'})")
        return PermanentError(f"Google API {status}: {_http_error_message(exc)}")
    if isinstance(exc, RefreshError):
        return BlockedError(
            "google",
            "the refresh token was revoked or expired; run `gmail-agent auth`. "
            "OAuth apps in Testing mode get refresh tokens that expire after 7 days.",
        )
    if isinstance(
        exc,
        TransportError | httplib2.HttpLib2Error | TimeoutError | socket.timeout | ssl.SSLError,
    ):
        return TransientError(f"network error talking to Google: {exc!r}")
    if isinstance(exc, ConnectionError | OSError):
        return TransientError(f"network error talking to Google: {exc!r}")
    return None


def _http_error_details(exc: HttpError) -> dict[str, Any]:
    try:
        payload = json.loads(exc.content.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return {}
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, dict) else {}


def _http_error_reason(exc: HttpError) -> str:
    errors = _http_error_details(exc).get("errors") or [{}]
    reason = errors[0].get("reason", "") if isinstance(errors[0], dict) else ""
    return str(reason)


def _http_error_message(exc: HttpError) -> str:
    return str(_http_error_details(exc).get("message") or exc.reason or "request failed")
