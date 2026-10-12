"""REST and SSE endpoints.

Every handler and dependency is `async def` on purpose: FastAPI runs plain `def`
handlers in a thread pool, and the store's SQLite connection belongs to the event
loop thread, as does the worker.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent

from gmail_operations_agent.api.events import EventHub
from gmail_operations_agent.api.schemas import (
    MAX_BODY_CHARS,
    MAX_SUBJECT_CHARS,
    ActionOut,
    ApproveIn,
    BlockedOut,
    ConnectionOut,
    DemoOut,
    EmailOut,
    EventOut,
    LatencyOut,
    LlmStatsOut,
    MessageDetail,
    MessagePage,
    MessageSummary,
    PresetOut,
    QuotaOut,
    SettingsIn,
    StatsOut,
    StatusOut,
    TestEmailIn,
    TestEmailOut,
    UsageOut,
    WorkerOut,
)
from gmail_operations_agent.demo.service import (
    DemoLimitError,
    DemoService,
    DemoSessionGoneError,
    DemoUnavailableError,
    Quota,
    Session,
)
from gmail_operations_agent.domain import MessageState, Overrides
from gmail_operations_agent.pipeline import InvalidTransitionError
from gmail_operations_agent.runtime import Runtime
from gmail_operations_agent.store import MessageRecord, utcnow

DEMO_COOKIE = "demo_session"

router = APIRouter(prefix="/api")


# --- dependencies ----------------------------------------------------------------------


@dataclass(frozen=True)
class Viewer:
    owner: str  # '' for the Gmail agent; a sandbox in the demo
    session: Session | None


async def get_runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


async def get_hub(request: Request) -> EventHub:
    hub: EventHub = request.app.state.hub
    return hub


RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


async def get_viewer(request: Request, response: Response, runtime: RuntimeDep) -> Viewer:
    """The Gmail agent has a single owner; in the demo, the cookie picks the visitor's sandbox.

    Only a GET creates a sandbox: a change sent without one (an expired cookie, or a
    request whose body then fails validation) must not leave orphan sandboxes behind.
    """
    if runtime.demo is None:
        return Viewer("", None)
    client = request.client.host if request.client else "unknown"
    token = request.cookies.get(DEMO_COOKIE)
    try:
        session = runtime.demo.session(token, client, create=request.method == "GET")
    except DemoLimitError as exc:
        raise HTTPException(429, str(exc)) from exc
    except DemoSessionGoneError as exc:
        raise HTTPException(410, str(exc)) from exc
    if session.new_token:
        _set_cookie(request, response, runtime.demo, session.new_token)
    return Viewer(session.owner, session)


ViewerDep = Annotated[Viewer, Depends(get_viewer)]


def _set_cookie(request: Request, response: Response, demo: DemoService, token: str) -> None:
    response.set_cookie(
        DEMO_COOKIE,
        token,
        max_age=int(demo.limits.sandbox_ttl_hours * 3600),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def _demo(runtime: Runtime, viewer: Viewer) -> tuple[DemoService, Session]:
    if runtime.demo is None or viewer.session is None:
        raise HTTPException(404, "Not available outside the demo.")
    return runtime.demo, viewer.session


def _own(runtime: Runtime, viewer: Viewer, message_id: str) -> MessageRecord:
    record = runtime.store.get_message(message_id)
    if record is None or record.owner != viewer.owner:
        raise HTTPException(404, "No such message.")
    return record


# --- status and settings ---------------------------------------------------------------


@router.get("/health", include_in_schema=False)
async def health() -> dict[str, bool]:
    return {"ok": True}


@router.get("/status")
async def status(runtime: RuntimeDep, viewer: ViewerDep) -> StatusOut:
    worker = runtime.worker.status
    blocked = None
    if worker.blocked_service:
        blocked = BlockedOut(
            service=worker.blocked_service,
            reason=worker.blocked_reason or "",
            until=worker.blocked_until,
        )
    demo = runtime.demo is not None
    settings = runtime.settings
    return StatusOut(
        source="demo" if demo else "gmail",
        mode=runtime.pipeline.mode(viewer.owner),
        model=runtime.pipeline.llm.model,
        worker=WorkerOut(
            running=worker.running,
            last_poll_at=worker.last_poll_at,
            last_error=worker.last_error,
            blocked=blocked,
            in_flight=len(worker.in_flight),
        ),
        connections={
            "gmail": ConnectionOut(enabled=True, sandbox=demo),
            "notion": ConnectionOut(enabled=demo or settings.notion_enabled, sandbox=demo),
            "sheets": ConnectionOut(enabled=demo or settings.sheets_enabled, sandbox=demo),
        },
    )


@router.put("/settings")
async def update_settings(body: SettingsIn, runtime: RuntimeDep, viewer: ViewerDep) -> StatusOut:
    runtime.pipeline.set_mode(body.mode, viewer.owner)
    return await status(runtime, viewer)


@router.get("/stats")
async def stats(
    runtime: RuntimeDep, viewer: ViewerDep, hours: Annotated[int, Query(ge=1, le=720)] = 24
) -> StatsOut:
    raw = runtime.store.stats(utcnow() - timedelta(hours=hours), viewer.owner)
    counts = {state.value: raw["by_state"].get(state.value, 0) for state in MessageState}
    counts["all"] = sum(raw["by_state"].values())
    return StatsOut(
        hours=hours,
        counts=counts,
        by_category=raw["by_category"],
        llm=LlmStatsOut(
            calls=raw["llm_calls"],
            failures=raw["llm_failures"],
            cost_usd=raw["llm_cost_usd"],
            cost_per_1k_usd=raw["llm_cost_per_1k_usd"],
            latency_ms=LatencyOut(
                avg=raw["llm_avg_latency_ms"],
                p50=raw["llm_p50_latency_ms"],
                p95=raw["llm_p95_latency_ms"],
            ),
        ),
    )


# --- messages --------------------------------------------------------------------------


@router.get("/messages")
async def list_messages(
    runtime: RuntimeDep,
    viewer: ViewerDep,
    state: Annotated[list[MessageState] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> MessagePage:
    cursor = runtime.store.last_event_id()  # taken first: the page reflects at least this much
    records = runtime.store.list_messages(viewer.owner, state, limit, before, q)
    return MessagePage(
        items=[MessageSummary.of(record) for record in records],
        next_before=records[-1].created_at if len(records) == limit else None,
        cursor=cursor,
        counts=runtime.store.count_by_state(viewer.owner),
    )


@router.get("/messages/{message_id}")
async def get_message(message_id: str, runtime: RuntimeDep, viewer: ViewerDep) -> MessageDetail:
    return _detail(runtime, _own(runtime, viewer, message_id))


@router.post("/messages/{message_id}/approve")
async def approve(
    message_id: str, runtime: RuntimeDep, viewer: ViewerDep, body: ApproveIn | None = None
) -> MessageDetail:
    _own(runtime, viewer, message_id)
    overrides = body.overrides() if body else None
    _transition(lambda: runtime.pipeline.approve(message_id, overrides))
    runtime.worker.wake()
    return _detail(runtime, _own(runtime, viewer, message_id))


@router.post("/messages/{message_id}/reject")
async def reject(message_id: str, runtime: RuntimeDep, viewer: ViewerDep) -> MessageDetail:
    _own(runtime, viewer, message_id)
    _transition(lambda: runtime.pipeline.reject(message_id))
    runtime.worker.wake()
    return _detail(runtime, _own(runtime, viewer, message_id))


@router.post("/messages/{message_id}/retry")
async def retry(message_id: str, runtime: RuntimeDep, viewer: ViewerDep) -> MessageDetail:
    _own(runtime, viewer, message_id)
    _transition(lambda: runtime.pipeline.retry(message_id))
    runtime.worker.wake()
    return _detail(runtime, _own(runtime, viewer, message_id))


def _transition(action: Callable[[], None]) -> None:
    try:
        action()
    except InvalidTransitionError as exc:
        raise HTTPException(409, str(exc)) from exc


def _detail(runtime: Runtime, record: MessageRecord) -> MessageDetail:
    triage = record.effective_triage
    actions = []
    for action in runtime.store.get_actions(record.id):
        preview = action.preview
        sink = runtime.pipeline.sink(action.kind)
        if not preview and triage and sink:
            preview = sink.preview(record.email, triage)
        actions.append(ActionOut.of(action, preview))
    usage = runtime.store.last_usage(record.id)
    email = record.email
    return MessageDetail(
        **MessageSummary.of(record).model_dump(),
        email=EmailOut(
            to=email.to,
            reply_to=email.reply_to,
            body=email.body,
            body_truncated=email.body_truncated,
            attachments=email.attachments,
            is_automated=email.is_automated,
            web_url=email.web_url,
        ),
        triage=triage,
        edited=record.overrides != Overrides(),
        notes=record.notes,
        decision=record.decision,
        actions=actions,
        events=[
            EventOut.of(event)
            for event in runtime.store.events_after(0, limit=200, message_id=record.id)
        ],
        usage=UsageOut.of(usage) if usage else None,
    )


# --- live updates ----------------------------------------------------------------------


@router.get("/events", response_class=EventSourceResponse)
async def events(
    viewer: ViewerDep,
    hub: Annotated[EventHub, Depends(get_hub)],
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> AsyncIterator[ServerSentEvent]:
    """Live events for the viewer's messages.

    Start with `after` = the `cursor` of the list you loaded; on reconnect the browser
    sends `Last-Event-ID` itself, which takes precedence.
    """
    start = last_event_id if last_event_id is not None else after
    async for message in hub.stream(viewer.owner, start):
        yield message


# --- demo ------------------------------------------------------------------------------


def _quota(quota: Quota) -> QuotaOut:
    return QuotaOut(limit=quota.limit, used=quota.used, left=quota.left, resets_at=quota.resets_at)


@router.get("/demo")
async def demo_info(runtime: RuntimeDep, viewer: ViewerDep) -> DemoOut:
    demo, session = _demo(runtime, viewer)
    return DemoOut(
        quota=_quota(demo.quota(session.visitor)),
        live=demo.llm.live_available(),
        presets=[PresetOut(**vars(preset)) for preset in demo.data.presets],
        max_subject_chars=MAX_SUBJECT_CHARS,
        max_body_chars=MAX_BODY_CHARS,
    )


@router.post("/demo/emails", status_code=202)
async def send_test_email(
    body: TestEmailIn, runtime: RuntimeDep, viewer: ViewerDep
) -> TestEmailOut:
    demo, session = _demo(runtime, viewer)
    try:
        record, recorded = demo.submit(
            session, body.sender_name, body.sender_address, body.subject, body.body
        )
    except DemoLimitError as exc:
        raise HTTPException(429, str(exc)) from exc
    except DemoUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    return TestEmailOut(
        message=MessageSummary.of(record),
        recorded=recorded,
        quota=_quota(demo.quota(session.visitor)),
    )


@router.post("/demo/reset")
async def reset_demo(
    request: Request, response: Response, runtime: RuntimeDep, viewer: ViewerDep
) -> StatusOut:
    """Start over with a fresh copy of the seed inbox."""
    demo, session = _demo(runtime, viewer)
    client = request.client.host if request.client else "unknown"
    try:
        fresh = demo.reset(session.owner, client)
    except DemoLimitError as exc:
        raise HTTPException(429, str(exc)) from exc
    assert fresh.new_token
    _set_cookie(request, response, demo, fresh.new_token)
    return await status(runtime, Viewer(fresh.owner, fresh))
