"""Google OAuth: an interactive login once (`gmail-agent auth`), silent refresh afterwards.

The worker never opens a browser. If the token cannot be refreshed it stops with a
clear message instead of hanging on a login prompt nobody sees.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import cast

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gmail_operations_agent.errors import BlockedError, ConfigError

logger = logging.getLogger(__name__)

# gmail.modify: read, label, create drafts. Unlike https://mail.google.com/ it cannot
# delete mail permanently.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def required_scopes(sheets_enabled: bool) -> list[str]:
    return [GMAIL_SCOPE, SHEETS_SCOPE] if sheets_enabled else [GMAIL_SCOPE]


def login(credentials_file: Path, token_file: Path, scopes: list[str]) -> Credentials:
    if not credentials_file.exists():
        raise ConfigError(
            f"{credentials_file} not found. Create an OAuth client (Desktop app) in Google "
            "Cloud Console and save its JSON there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    creds = cast(Credentials, flow.run_local_server(port=0))
    _save(creds, token_file)
    return creds


def load_credentials(token_file: Path, scopes: list[str]) -> Credentials:
    if not token_file.exists():
        raise ConfigError(f"{token_file} not found. Run `gmail-agent auth` first.")
    creds: Credentials = Credentials.from_authorized_user_file(str(token_file))
    if not creds.has_scopes(scopes):
        raise ConfigError(
            f"{token_file} was issued for other permissions. Run `gmail-agent auth` again."
        )
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise BlockedError(
                "google",
                "the refresh token was revoked or expired; run `gmail-agent auth`. "
                "OAuth apps in Testing mode get refresh tokens that expire after 7 days.",
            ) from exc
        _save(creds, token_file)
    return creds


def _save(creds: Credentials, token_file: Path) -> None:
    # Write to a temp file and rename: a crash never leaves a half-written token.
    token_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=token_file.parent, prefix=".token-")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(creds.to_json())
    os.replace(tmp, token_file)
    logger.info("Saved Google token to %s", token_file)
