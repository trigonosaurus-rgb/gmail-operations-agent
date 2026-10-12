"""Request and response models. Requests carry length limits; nothing unbounded gets in."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from gmail_operations_agent.domain import (
    NEEDS_APPROVAL,
    ActionKind,
    ActionStatus,
    Category,
    Decision,
    MessageState,
    Overrides,
    Priority,
    Risk,
    Triage,
    Usage,
)
from gmail_operations_agent.store import ActionRecord, Event, MessageRecord

MAX_SUBJECT_CHARS = 200
MAX_BODY_CHARS = 5_000

# --- requests --------------------------------------------------------------------------


class ApproveIn(BaseModel):
    """Edits made in review. Empty fields keep the model's text."""

    reply_body: str | None = Field(None, max_length=10_000)
    task_title: str | None = Field(None, max_length=200)
    task_description: str | None = Field(None, max_length=5_000)
    skip: list[ActionKind] = Field(default_factory=list, max_length=len(ActionKind))

    def overrides(self) -> Overrides | None:
        if not (self.reply_body or self.task_title or self.task_description or self.skip):
            return None
        return Overrides(**self.model_dump())


class SettingsIn(BaseModel):
    mode: Literal["review", "auto"]


class TestEmailIn(BaseModel):
    sender_name: str = Field("", max_length=100)
    sender_address: str = Field(max_length=254, pattern=r"^[^\s@<>\"]+@[^\s@<>\"]+\.[^\s@<>\"]+$")
    subject: str = Field(min_length=1, max_length=MAX_SUBJECT_CHARS)
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)


# --- responses -------------------------------------------------------------------------


class UsageOut(BaseModel):
    model: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float | None
    recorded: bool  # replayed from an eval run in the demo, not a live call

    @classmethod
    def of(cls, usage: Usage) -> "UsageOut":
        return cls(
            model=usage.model,
            input_tokens=usage.input_tokens,
            cached_tokens=usage.cached_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            cost_usd=usage.cost_usd,
            recorded=usage.provider == "replay",
        )


class MessageSummary(BaseModel):
    id: str
    state: MessageState
    sender_name: str
    sender_address: str
    subject: str
    received_at: datetime | None
    summary: str | None
    category: Category | None
    priority: Priority | None
    risk: Risk | None
    has_task: bool
    has_reply: bool
    attempts: int
    next_attempt_at: datetime | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, record: MessageRecord) -> "MessageSummary":
        triage = record.effective_triage
        email = record.email
        return cls(
            id=record.id,
            state=record.state,
            sender_name=email.sender_name,
            sender_address=email.sender_address,
            subject=email.subject,
            received_at=email.received_at,
            summary=triage.summary if triage else None,
            category=triage.category if triage else None,
            priority=triage.priority if triage else None,
            risk=triage.risk if triage else None,
            has_task=bool(triage and triage.task),
            has_reply=bool(triage and triage.reply),
            attempts=record.attempts,
            next_attempt_at=record.next_attempt_at,
            error=record.last_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class EmailOut(BaseModel):
    to: str
    reply_to: str | None
    body: str
    body_truncated: bool
    attachments: list[str]
    is_automated: bool
    web_url: str | None


class ActionOut(BaseModel):
    kind: ActionKind
    status: ActionStatus
    needs_approval: bool  # waits for a person in review mode
    attempts: int
    preview: dict[str, Any]  # what was (or would be) created
    url: str | None
    error: str | None
    updated_at: datetime

    @classmethod
    def of(cls, action: ActionRecord, preview: dict[str, Any]) -> "ActionOut":
        return cls(
            kind=action.kind,
            status=action.status,
            needs_approval=action.kind in NEEDS_APPROVAL,
            attempts=action.attempts,
            preview=preview,
            url=action.url,
            error=action.last_error,
            updated_at=action.updated_at,
        )


class EventOut(BaseModel):
    id: int
    message_id: str | None
    type: str
    data: dict[str, Any]
    created_at: datetime

    @classmethod
    def of(cls, event: Event) -> "EventOut":
        return cls(
            id=event.id,
            message_id=event.message_id,
            type=event.type,
            data=event.data,
            created_at=event.created_at,
        )


class MessageDetail(MessageSummary):
    email: EmailOut
    triage: Triage | None  # with the reviewer's edits applied
    edited: bool
    notes: list[str]  # why guardrails removed a task or a reply
    decision: Decision | None
    actions: list[ActionOut]
    events: list[EventOut]
    usage: UsageOut | None


class MessagePage(BaseModel):
    items: list[MessageSummary]
    next_before: datetime | None  # pass as `before` for the next page
    cursor: int  # pass to /api/events as `after` to get every change since this page
    counts: dict[MessageState, int]  # the whole inbox by state, ignoring filters and search


class LatencyOut(BaseModel):
    avg: int | None
    p50: int | None
    p95: int | None


class LlmStatsOut(BaseModel):
    calls: int
    failures: int
    cost_usd: float
    cost_per_1k_usd: float | None
    latency_ms: LatencyOut


class StatsOut(BaseModel):
    hours: int
    counts: dict[str, int]  # by state, plus "all"
    by_category: dict[str, int]
    llm: LlmStatsOut


class BlockedOut(BaseModel):
    service: str
    reason: str
    until: datetime | None


class WorkerOut(BaseModel):
    running: bool
    last_poll_at: datetime | None
    last_error: str | None
    blocked: BlockedOut | None
    in_flight: int


class ConnectionOut(BaseModel):
    enabled: bool
    sandbox: bool  # demo: records what would happen instead of calling the service


class StatusOut(BaseModel):
    source: Literal["gmail", "demo"]
    mode: Literal["review", "auto"]
    model: str
    worker: WorkerOut
    connections: dict[str, ConnectionOut]  # gmail, notion, sheets


class QuotaOut(BaseModel):
    limit: int
    used: int
    left: int
    resets_at: datetime


class PresetOut(BaseModel):
    id: str
    label: str
    sender_name: str
    sender_address: str
    subject: str
    body: str


class DemoOut(BaseModel):
    quota: QuotaOut
    live: bool  # false: only the presets work (no key, or the monthly budget is spent)
    presets: list[PresetOut]
    max_subject_chars: int
    max_body_chars: int


class TestEmailOut(BaseModel):
    message: MessageSummary
    recorded: bool  # a preset: replays the recorded run instead of calling the model
    quota: QuotaOut
