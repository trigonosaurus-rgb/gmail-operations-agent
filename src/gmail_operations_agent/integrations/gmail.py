"""Gmail as a mail source (label-based processing marker) and as a drafts sink."""

import base64
import logging
import re
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr

from gmail_operations_agent.domain import ActionKind, ActionResult, Email, Triage
from gmail_operations_agent.errors import PermanentError
from gmail_operations_agent.integrations.base import RawMessage
from gmail_operations_agent.integrations.google_api import NUM_RETRIES, GoogleApi

logger = logging.getLogger(__name__)

MAX_MESSAGES_PER_POLL = 200
_REPLY_PREFIX = re.compile(r"^\s*((re|aw|sv|antw|ответ)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)


def thread_url(thread_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"


def label_query(name: str) -> str:
    # Gmail search spells nested labels and spaces with dashes: Agent/Processed -> agent-processed.
    return re.sub(r"[/\s]+", "-", name.strip()).lower()


class GmailSource:
    """Processes inbox messages that do not carry the 'processed' label yet.

    The label, not UNREAD, is the marker: the owner can read mail on their phone
    without the agent skipping it, and the agent does not hide unread mail from them.
    """

    name = "gmail"

    def __init__(
        self,
        api: GoogleApi,
        processed_label: str,
        lookback_days: int = 7,
        mark_as_read: bool = False,
    ) -> None:
        self._api = api
        self._label_name = processed_label
        self._lookback_days = lookback_days
        self._mark_as_read = mark_as_read
        self._label_id: str | None = None

    async def ensure_label(self) -> str:
        """Find or create the label (and its parents for nested names)."""
        if self._label_id:
            return self._label_id
        response = await self._api.call(
            lambda: (
                self._api.gmail()
                .users()
                .labels()
                .list(userId="me")
                .execute(num_retries=NUM_RETRIES)
            )
        )
        existing = {label["name"]: label["id"] for label in response.get("labels", [])}
        parts = self._label_name.split("/")
        for depth in range(1, len(parts) + 1):
            name = "/".join(parts[:depth])
            if name not in existing:
                created = await self._api.call(
                    lambda name=name: (
                        self._api.gmail()  # type: ignore[misc]
                        .users()
                        .labels()
                        .create(
                            userId="me",
                            body={
                                "name": name,
                                "labelListVisibility": "labelShow",
                                "messageListVisibility": "show",
                            },
                        )
                        .execute(num_retries=NUM_RETRIES)
                    )
                )
                existing[name] = created["id"]
                logger.info("Created Gmail label %s", name)
        self._label_id = existing[self._label_name]
        return self._label_id

    async def poll(self, is_known: Callable[[str], bool]) -> list[RawMessage]:
        await self.ensure_label()
        query = f"in:inbox -label:{label_query(self._label_name)} newer_than:{self._lookback_days}d"
        ids: list[str] = []
        page_token: str | None = None
        while len(ids) < MAX_MESSAGES_PER_POLL:
            response = await self._api.call(
                lambda token=page_token: (
                    self._api.gmail()  # type: ignore[misc]
                    .users()
                    .messages()
                    .list(userId="me", q=query, maxResults=100, pageToken=token)
                    .execute(num_retries=NUM_RETRIES)
                )
            )
            ids += [message["id"] for message in response.get("messages", [])]
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        fresh = [message_id for message_id in ids if not is_known(message_id)]
        messages = []
        for message_id in reversed(fresh):  # the API lists newest first
            try:
                messages.append(await self._fetch(message_id))
            except PermanentError as exc:  # e.g. deleted between list and get
                logger.warning("Skipping message %s: %s", message_id, exc)
        return messages

    async def _fetch(self, message_id: str) -> RawMessage:
        response = await self._api.call(
            lambda: (
                self._api.gmail()
                .users()
                .messages()
                .get(userId="me", id=message_id, format="raw")
                .execute(num_retries=NUM_RETRIES)
            )
        )
        thread_id = response["threadId"]
        return RawMessage(
            id=message_id,
            thread_id=thread_id,
            raw=base64.urlsafe_b64decode(response["raw"]),
            web_url=thread_url(thread_id),
        )

    async def mark_processed(self, email: Email) -> ActionResult:
        label_id = await self.ensure_label()
        body: dict[str, list[str]] = {"addLabelIds": [label_id]}
        if self._mark_as_read:
            body["removeLabelIds"] = ["UNREAD"]
        await self._api.call(
            lambda: (
                self._api.gmail()
                .users()
                .messages()
                .modify(userId="me", id=email.id, body=body)  # type: ignore[arg-type]
                .execute(num_retries=NUM_RETRIES)
            )
        )
        return ActionResult(
            external_id=label_id,
            preview={"label": self._label_name, "marked_read": self._mark_as_read},
        )


def reply_subject(subject: str) -> str:
    return f"Re: {_REPLY_PREFIX.sub('', subject).strip() or '(no subject)'}"


def build_reply(email: Email, body: str) -> EmailMessage:
    message = EmailMessage()
    message["To"] = (
        formataddr((email.sender_name, email.sender_address))
        if not email.reply_to
        else email.reply_to
    )
    message["Subject"] = reply_subject(email.subject)
    if email.message_id_header:
        message["In-Reply-To"] = email.message_id_header
        message["References"] = " ".join(
            part for part in (email.references, email.message_id_header) if part
        )
    message.set_content(body)
    return message


class GmailDraftSink:
    """Creates a reply draft in the original thread. Drafts are never sent automatically."""

    kind = ActionKind.GMAIL_DRAFT

    def __init__(self, api: GoogleApi) -> None:
        self._api = api

    def preview(self, email: Email, triage: Triage) -> dict[str, object]:
        message = build_reply(email, triage.reply.body if triage.reply else "")
        return {
            "to": message["To"],
            "subject": message["Subject"],
            "body": triage.reply.body if triage.reply else "",
            "language": triage.reply.language if triage.reply else None,
        }

    async def find_existing(self, email: Email) -> ActionResult | None:
        """A draft in the thread that answers this exact message."""
        if not email.message_id_header:
            return None
        thread = await self._api.call(
            lambda: (
                self._api.gmail()
                .users()
                .threads()
                .get(
                    userId="me",
                    id=email.thread_id,
                    format="metadata",
                    metadataHeaders=["In-Reply-To"],
                )
                .execute(num_retries=NUM_RETRIES)
            )
        )
        for message in thread.get("messages", []):
            if "DRAFT" not in message.get("labelIds", []):
                continue
            headers = message.get("payload", {}).get("headers", [])
            if any(
                h.get("name", "").lower() == "in-reply-to"
                and h.get("value") == email.message_id_header
                for h in headers
            ):
                return ActionResult(external_id=message.get("id"), url=email.web_url)
        return None

    async def execute(self, email: Email, triage: Triage) -> ActionResult:
        if not triage.reply:
            raise PermanentError("no reply to draft")
        message = build_reply(email, triage.reply.body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        # No client-side retries for a create: a retried 5xx could leave two drafts.
        # The pipeline retries instead, after checking find_existing.
        draft = await self._api.call(
            lambda: (
                self._api.gmail()
                .users()
                .drafts()
                .create(userId="me", body={"message": {"raw": raw, "threadId": email.thread_id}})
                .execute()
            )
        )
        return ActionResult(
            external_id=draft.get("id"), url=email.web_url, preview=self.preview(email, triage)
        )
