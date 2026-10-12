"""The HTTP API over a fake-backed pipeline: lists, details, decisions, limits and live events."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from gmail_operations_agent.api.app import create_app
from gmail_operations_agent.api.events import EventHub
from gmail_operations_agent.config import Settings
from gmail_operations_agent.domain import ActionKind, Category, MessageState, Priority
from gmail_operations_agent.errors import PermanentError
from gmail_operations_agent.integrations.base import MarkProcessedSink
from gmail_operations_agent.pipeline import Pipeline, PipelineConfig
from gmail_operations_agent.runtime import Runtime
from gmail_operations_agent.store import Store
from gmail_operations_agent.worker import Worker
from tests.fakes import FakeClock, FakeLLM, FakeSink, FakeSource, make_email, make_triage


class Api:
    def __init__(self, store: Store, clock: FakeClock, tmp_path: Path) -> None:
        self.store = store
        self.llm = FakeLLM()
        self.source = FakeSource()
        self.notion = FakeSink(ActionKind.NOTION_TASK)
        self.draft = FakeSink(ActionKind.GMAIL_DRAFT)
        self.pipeline = Pipeline(
            store,
            self.llm,
            [self.notion, self.draft, MarkProcessedSink(self.source)],
            PipelineConfig(mode="review"),
            clock=clock,
        )
        self.worker = Worker(self.pipeline, self.source, clock=clock)
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            openai_api_key=None,
            web_dist_dir=tmp_path / "no-ui",
        )
        self.runtime = Runtime(settings, store, self.pipeline, self.worker, self.source)
        self.app = create_app(self.runtime, run_worker=False)

    async def add(self, message_id: str = "m1", **overrides: object) -> str:
        self.pipeline.add_email(make_email(message_id, **overrides))
        await self.worker.drain()
        return message_id


@pytest.fixture
def api(store: Store, clock: FakeClock, tmp_path: Path) -> Api:
    return Api(store, clock, tmp_path)


@pytest.fixture
async def client(api: Api) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def test_list_shows_triage_summary_and_filters_by_state(
    api: Api, client: httpx.AsyncClient
) -> None:
    api.llm.script = [make_triage(), make_triage(task=None, reply=None, summary="FYI only.")]
    await api.add("review-me")
    await api.add("fyi", subject="Weekly digest")

    page = (await client.get("/api/messages")).json()
    assert [item["id"] for item in page["items"]] == ["fyi", "review-me"]  # newest first
    review = page["items"][1]
    assert review["state"] == "awaiting_approval"
    assert review["summary"].startswith("Anna asks")
    assert review["priority"] == "high"
    assert review["has_task"]
    assert review["has_reply"]
    assert page["cursor"] > 0

    only_review = (await client.get("/api/messages?state=awaiting_approval")).json()
    assert [item["id"] for item in only_review["items"]] == ["review-me"]
    # Counts cover the whole inbox, so filter tabs can show them whatever is selected.
    assert only_review["counts"]["awaiting_approval"] == 1
    assert sum(only_review["counts"].values()) == 2


async def test_search_ignores_case_in_any_alphabet(api: Api, client: httpx.AsyncClient) -> None:
    await api.add("ru", subject="Счёт на оплату", sender_name="ООО Ромашка")
    await api.add("en", subject="Invoice overdue")
    await api.add("pct", subject="100% discount")

    async def ids(q: str) -> list[str]:
        response = await client.get("/api/messages", params={"q": q})
        return [item["id"] for item in response.json()["items"]]

    assert await ids("СЧЁТ") == ["ru"]
    assert await ids("ромашка") == ["ru"]
    assert await ids("OVERDUE") == ["en"]
    assert await ids("%") == ["pct"]  # LIKE wildcards are matched literally


async def test_pagination_with_before(api: Api, client: httpx.AsyncClient) -> None:
    for n in range(3):
        await api.add(f"m{n}")
    first = (await client.get("/api/messages?limit=2")).json()
    assert [item["id"] for item in first["items"]] == ["m2", "m1"]
    rest = (
        await client.get("/api/messages", params={"limit": 2, "before": first["next_before"]})
    ).json()
    assert [item["id"] for item in rest["items"]] == ["m0"]
    assert rest["next_before"] is None


async def test_detail_shows_previews_usage_and_activity(
    api: Api, client: httpx.AsyncClient
) -> None:
    await api.add()
    detail = (await client.get("/api/messages/m1")).json()

    assert detail["email"]["body"] == "Could you send a quote by Friday?"
    assert detail["triage"]["task"]["title"] == "Send a quote to Anna"
    kinds = {action["kind"]: action for action in detail["actions"]}
    assert kinds["notion_task"]["status"] == "pending"
    assert kinds["notion_task"]["needs_approval"] is True
    assert kinds["notion_task"]["preview"] == {"kind": "notion_task"}  # from the sink
    assert kinds["mark_processed"]["needs_approval"] is False
    assert detail["usage"]["input_tokens"] == 1000
    assert detail["usage"]["recorded"] is False
    assert "prompt_version" not in detail["usage"]  # nothing a user can act on
    assert [e["type"] for e in detail["events"]] == ["ingested", "triaged", "awaiting_approval"]


async def test_approve_with_edits_runs_the_edited_actions(
    api: Api, client: httpx.AsyncClient
) -> None:
    await api.add()
    response = await client.post(
        "/api/messages/m1/approve",
        json={"reply_body": "Hi Anna, quote attached.", "skip": ["notion_task"]},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "acting"
    assert response.json()["edited"] is True

    await api.worker.drain()
    detail = (await client.get("/api/messages/m1")).json()
    assert detail["state"] == "done"
    assert detail["decision"] == "approved"
    assert detail["triage"]["reply"]["body"] == "Hi Anna, quote attached."
    assert api.notion.executed == []
    assert api.draft.executed == ["m1"]
    approved = next(e for e in detail["events"] if e["type"] == "approved")
    assert approved["data"] == {"by": "you"}


async def test_reject_labels_only(api: Api, client: httpx.AsyncClient) -> None:
    await api.add()
    assert (await client.post("/api/messages/m1/reject")).status_code == 200
    await api.worker.drain()
    detail = (await client.get("/api/messages/m1")).json()
    assert detail["state"] == "rejected"
    assert api.notion.executed == api.draft.executed == []
    assert api.source.processed == ["m1"]


async def test_retry_dead_letter_and_conflicts(api: Api, client: httpx.AsyncClient) -> None:
    api.llm.script = [PermanentError("model refused"), make_triage()]
    await api.add()
    assert (await client.get("/api/messages/m1")).json()["state"] == "dead"

    assert (await client.post("/api/messages/m1/approve")).status_code == 409
    response = await client.post("/api/messages/m1/retry")
    assert response.status_code == 200
    assert response.json()["state"] == "new"
    await api.worker.drain()
    assert (await client.get("/api/messages/m1")).json()["state"] == "awaiting_approval"
    assert (await client.post("/api/messages/m1/retry")).status_code == 409
    assert (await client.post("/api/messages/nope/retry")).status_code == 404


async def test_review_mode_switch_applies_to_new_mail(api: Api, client: httpx.AsyncClient) -> None:
    status = (await client.put("/api/settings", json={"mode": "auto"})).json()
    assert status["mode"] == "auto"
    await api.add()
    assert (await client.get("/api/messages/m1")).json()["state"] == "done"
    assert (await client.get("/api/status")).json()["mode"] == "auto"


async def test_stats_counts_and_latency(api: Api, client: httpx.AsyncClient) -> None:
    api.llm.script = [make_triage(), make_triage(priority=Priority.LOW, task=None, reply=None)]
    await api.add("a")
    await api.add("b")
    stats = (await client.get("/api/stats")).json()
    assert stats["counts"]["all"] == 2
    assert stats["counts"]["awaiting_approval"] == 1
    assert stats["counts"]["done"] == 1
    assert stats["counts"]["dead"] == 0
    assert stats["by_category"] == {"lead": 2}
    assert stats["llm"]["calls"] == 2
    assert stats["llm"]["cost_per_1k_usd"] == pytest.approx(0.2)
    assert stats["llm"]["latency_ms"]["p50"] == 5


async def test_stats_cover_only_the_chosen_period(
    api: Api, client: httpx.AsyncClient, clock: FakeClock
) -> None:
    """Every number on the page describes the same mail: what arrived in the period."""
    api.llm.script = [make_triage(), make_triage(category=Category.INVOICE)]
    await api.add("old")
    clock.advance(48 * 3600)
    await api.add("new")

    day = (await client.get("/api/stats", params={"hours": 24})).json()
    assert day["counts"]["all"] == 1
    assert day["by_category"] == {"invoice": 1}
    assert day["llm"]["calls"] == 1

    week = (await client.get("/api/stats", params={"hours": 168})).json()
    assert week["counts"]["all"] == 2
    assert week["by_category"] == {"lead": 1, "invoice": 1}
    assert week["llm"]["calls"] == 2


async def test_status_reports_source_and_connections(client: httpx.AsyncClient) -> None:
    status = (await client.get("/api/status")).json()
    assert status["source"] == "gmail"
    assert status["mode"] == "review"
    assert status["connections"]["notion"] == {"enabled": False, "sandbox": False}
    assert status["worker"]["blocked"] is None


async def test_input_limits(api: Api, client: httpx.AsyncClient) -> None:
    await api.add()
    too_long = await client.post("/api/messages/m1/approve", json={"reply_body": "x" * 10_001})
    assert too_long.status_code == 422
    huge = await client.post(
        "/api/messages/m1/approve",
        content=b"{" + b" " * 70_000 + b"}",
        headers={"content-type": "application/json"},
    )
    assert huge.status_code == 413
    assert (await client.get("/api/messages", params={"q": "x" * 201})).status_code == 422


async def test_security_headers(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/status")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"
    docs = await client.get("/docs")
    assert "cdn.jsdelivr.net" in docs.headers["content-security-policy"]


async def test_frontend_is_served_when_built(
    store: Store, clock: FakeClock, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>UI</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("TOPSECRET")
    api = Api(store, clock, tmp_path)
    api.runtime.settings.web_dist_dir = dist
    app = create_app(api.runtime, run_worker=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        assert "<title>UI</title>" in (await http.get("/inbox/m1")).text  # client-side route
        assert (await http.get("/assets/app.js")).text == "console.log(1)"
        assert (await http.get("/api/nothing")).status_code == 404
        for escape in ("/%2e%2e/secret.txt", "/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt"):
            assert "TOPSECRET" not in (await http.get(escape)).text


# --- live events -----------------------------------------------------------------------


async def _take(stream: AsyncIterator[object], count: int) -> list[object]:
    items = []
    async for item in stream:
        items.append(item)
        if len(items) == count:
            break
    return items


async def test_event_stream_replays_after_cursor_then_goes_live(api: Api) -> None:
    hub: EventHub = api.app.state.hub
    await api.add("m1")
    cursor = api.store.last_event_id()
    await api.add("m2")  # missed while "disconnected"

    stream = hub.stream("", after=cursor)
    ready, *replayed = await _take(stream, 4)
    assert ready.event == "ready"  # type: ignore[attr-defined]
    assert [m.event for m in replayed] == ["ingested", "triaged", "awaiting_approval"]  # type: ignore[attr-defined]
    assert replayed[-1].data["message"]["state"] == "awaiting_approval"  # type: ignore[attr-defined]

    next_live = asyncio.create_task(_take(stream, 1))
    await asyncio.sleep(0)
    api.pipeline.reject("m2")
    [live] = await next_live
    assert live.event == "rejected"  # type: ignore[attr-defined]
    assert live.data["message"]["id"] == "m2"  # type: ignore[attr-defined]
    await stream.aclose()  # type: ignore[attr-defined]
    assert hub.subscribers == 0


async def test_stale_cursor_from_a_replaced_database_resets_the_client(api: Api) -> None:
    hub: EventHub = api.app.state.hub
    await api.add("m1")
    stream = hub.stream("", after=10_000)
    _ready, reset = await _take(stream, 2)
    assert reset.event == "reset"  # type: ignore[attr-defined]
    assert reset.data == {"cursor": api.store.last_event_id()}  # type: ignore[attr-defined]
    live = asyncio.create_task(_take(stream, 1))
    await asyncio.sleep(0)
    api.pipeline.reject("m1")
    [event] = await live
    assert event.event == "rejected"  # type: ignore[attr-defined]
    await stream.aclose()  # type: ignore[attr-defined]


async def test_event_stream_is_scoped_to_the_owner(api: Api) -> None:
    hub: EventHub = api.app.state.hub
    stream = hub.stream("someone-else", after=None)
    await _take(stream, 1)  # ready
    pending = asyncio.create_task(_take(stream, 1))
    await api.add("m1")  # owner ''
    await asyncio.sleep(0)
    assert not pending.done()
    pending.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await pending
    await stream.aclose()  # type: ignore[attr-defined]


async def test_slow_subscriber_is_dropped_not_blocking(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("gmail_operations_agent.api.events.QUEUE_SIZE", 2)
    hub: EventHub = api.app.state.hub
    stream = hub.stream("", after=None)
    await _take(stream, 1)
    await api.add("m1")  # three events into a queue of two: the stream is marked stale
    received = await _take(stream, 5)
    assert len(received) == 2  # what fit, then the stream ends so the client reconnects
    assert hub.subscribers == 0
    assert api.store.get_message("m1").state == MessageState.AWAITING_APPROVAL  # type: ignore[union-attr]


async def test_sse_over_a_real_socket_and_disconnect_cleanup(api: Api) -> None:
    """Through uvicorn: the wire format, Last-Event-ID, and cleanup when the client leaves."""
    import uvicorn

    await api.add("m1")
    hub: EventHub = api.app.state.hub
    config = uvicorn.Config(api.app, host="127.0.0.1", port=0, log_config=None, lifespan="off")
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        async with (
            httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http,
            http.stream("GET", "/api/events", headers={"Last-Event-ID": "1"}) as response,
        ):
            assert response.headers["content-type"].startswith("text/event-stream")
            lines: list[str] = []
            async for line in response.aiter_lines():
                lines.append(line)
                if line == "id: 3":
                    break
            assert "event: ready" in lines
            assert "event: triaged" in lines  # event 2, after the Last-Event-ID
            assert "event: ingested" not in lines  # event 1 was already seen
            assert hub.subscribers == 1
        for _ in range(100):  # the server notices the closed connection
            if hub.subscribers == 0:
                break
            await asyncio.sleep(0.02)
        assert hub.subscribers == 0
    finally:
        server.should_exit = True
        await serving
