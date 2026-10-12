"""Notion tasks: one page per actionable email, in a database (API version 2025-09-03)."""

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from notion_client import AsyncClient
from notion_client.errors import APIResponseError, HTTPResponseError, RequestTimeoutError

from gmail_operations_agent.domain import ActionKind, ActionResult, Email, Triage
from gmail_operations_agent.errors import AgentError, BlockedError, PermanentError, TransientError

logger = logging.getLogger(__name__)

TEXT_LIMIT = 2000  # characters per rich-text object
RICH_TEXT_ITEMS_LIMIT = 100  # rich-text objects per block


def chunk_text(text: str, size: int = TEXT_LIMIT) -> list[str]:
    """Split text into pieces Notion accepts, preferring line breaks and spaces."""
    chunks = []
    while len(text) > size:
        cut = max(text.rfind("\n", 0, size), text.rfind(" ", 0, size))
        if cut < size // 2:
            cut = size
        chunks.append(text[:cut])
        text = text[cut:].lstrip(" ")
    if text:
        chunks.append(text)
    return chunks


def rich_text(text: str, link: str | None = None) -> list[dict[str, Any]]:
    items = []
    for chunk in chunk_text(text):
        item: dict[str, Any] = {"type": "text", "text": {"content": chunk}}
        if link:
            item["text"]["link"] = {"url": link}
        items.append(item)
    return items


def paragraphs(text: str) -> list[dict[str, Any]]:
    items = rich_text(text)
    return [
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": group}}
        for group in (
            items[i : i + RICH_TEXT_ITEMS_LIMIT]
            for i in range(0, len(items), RICH_TEXT_ITEMS_LIMIT)
        )
    ]


@dataclass
class _Schema:
    data_source_id: str
    title: str
    priority: str | None
    email_id: str | None


def task_preview(triage: Triage) -> dict[str, object]:
    task = triage.task
    return {
        "title": task.title if task else "",
        "description": task.description if task else "",
        "priority": triage.priority.value,
        "due_date": task.due_date if task else None,
    }


class NotionSink:
    kind = ActionKind.NOTION_TASK

    def __init__(
        self,
        token: str,
        *,
        database_id: str | None,
        data_source_id: str | None = None,
        title_property: str = "Name",
        priority_property: str | None = "Priority",
        email_id_property: str | None = "Gmail ID",
        client: AsyncClient | None = None,
    ) -> None:
        self._client = client or AsyncClient(auth=token)
        self._database_id = database_id
        self._data_source_id = data_source_id
        self._wanted = (title_property, priority_property, email_id_property)
        self._schema: _Schema | None = None

    async def schema(self) -> _Schema:
        """Resolve the data source and check its properties once, with helpful errors."""
        if self._schema:
            return self._schema
        try:
            data_source_id = self._data_source_id or await self._single_data_source()
            source = await self._client.data_sources.retrieve(data_source_id=data_source_id)
        except Exception as exc:
            raise _classify(exc) from exc
        props: dict[str, Any] = source.get("properties", {})
        title_name, priority_name, email_id_name = self._wanted
        if props.get(title_name, {}).get("type") != "title":
            # Use whatever the title column is called instead of failing.
            detected = next((name for name, p in props.items() if p.get("type") == "title"), None)
            if detected is None:
                raise BlockedError("notion", "the data source has no title property")
            title_name = detected
        if priority_name and props.get(priority_name, {}).get("type") != "select":
            logger.warning("Notion: no select property %r; priority will not be set", priority_name)
            priority_name = None
        if email_id_name and props.get(email_id_name, {}).get("type") != "rich_text":
            logger.warning(
                "Notion: no text property %r; duplicate protection after crashes is off",
                email_id_name,
            )
            email_id_name = None
        self._schema = _Schema(data_source_id, title_name, priority_name, email_id_name)
        return self._schema

    async def _single_data_source(self) -> str:
        database = await self._client.databases.retrieve(database_id=self._database_id or "")
        sources = database.get("data_sources", [])
        if len(sources) != 1:
            names = ", ".join(s.get("name", s["id"]) for s in sources) or "none"
            raise BlockedError(
                "notion",
                f"the database has {len(sources)} data sources ({names}); "
                "set NOTION_DATA_SOURCE_ID",
            )
        return str(sources[0]["id"])

    def preview(self, email: Email, triage: Triage) -> dict[str, object]:
        return task_preview(triage)

    async def find_existing(self, email: Email) -> ActionResult | None:
        schema = await self.schema()
        if not schema.email_id:
            return None
        try:
            response = await self._client.data_sources.query(
                data_source_id=schema.data_source_id,
                filter={"property": schema.email_id, "rich_text": {"equals": email.id}},
                page_size=1,
            )
        except Exception as exc:
            raise _classify(exc) from exc
        results = response.get("results", [])
        if results:
            return ActionResult(external_id=results[0]["id"], url=results[0].get("url"))
        return None

    async def execute(self, email: Email, triage: Triage) -> ActionResult:
        if not triage.task:
            raise PermanentError("no task to create")
        schema = await self.schema()
        task = triage.task
        properties: dict[str, Any] = {
            schema.title: {"title": rich_text(task.title[:TEXT_LIMIT])[:1]},
        }
        if schema.priority:
            properties[schema.priority] = {"select": {"name": triage.priority.value.capitalize()}}
        if schema.email_id:
            properties[schema.email_id] = {"rich_text": rich_text(email.id)}

        children = paragraphs(task.description)
        if task.due_date:
            children += paragraphs(f"Due: {task.due_date}")
        children.append({"object": "block", "type": "divider", "divider": {}})
        children += paragraphs(f"From: {email.sender_display}\nSubject: {email.subject}")
        children.append(
            {"object": "block", "type": "quote", "quote": {"rich_text": rich_text(triage.summary)}}
        )
        if email.web_url:
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": rich_text("Open in Gmail", link=email.web_url)},
                }
            )
        try:
            page = await self._client.pages.create(
                parent={"type": "data_source_id", "data_source_id": schema.data_source_id},
                properties=properties,
                children=children,
            )
        except Exception as exc:
            raise _classify(exc) from exc
        return ActionResult(
            external_id=page["id"],
            url=page.get("url"),
            preview=self.preview(email, triage),
        )


def _classify(exc: Exception) -> Exception:
    if isinstance(exc, AgentError):
        return exc
    if isinstance(exc, RequestTimeoutError | httpx.TransportError):
        return TransientError(f"Notion unavailable: {exc}")
    if isinstance(exc, APIResponseError | HTTPResponseError):
        status = exc.status
        if status == 429 or status >= 500 or status == 409:
            return TransientError(f"Notion {status}: {exc}")
        if status == 401:
            return BlockedError("notion", "the integration token was rejected")
        if status in (403, 404):
            return BlockedError(
                "notion", "the database is not shared with the integration, or the ID is wrong"
            )
        return PermanentError(f"Notion rejected the page ({status}): {exc}")
    return exc
