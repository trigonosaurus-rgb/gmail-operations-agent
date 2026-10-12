"""Domain models shared by the pipeline, the store, the integrations and the API."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Category(StrEnum):
    LEAD = "lead"
    CLIENT = "client"
    INVOICE = "invoice"
    MEETING = "meeting"
    SUPPORT = "support"
    NEWSLETTER = "newsletter"
    NOTIFICATION = "notification"
    PERSONAL = "personal"
    SPAM = "spam"
    OTHER = "other"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Risk(StrEnum):
    NONE = "none"
    SPAM = "spam"
    PHISHING = "phishing"
    PROMPT_INJECTION = "prompt_injection"


class Email(BaseModel):
    """A parsed incoming message. The body is cleaned text, ready for the model."""

    id: str
    thread_id: str
    source: str
    message_id_header: str | None = None
    references: str | None = None
    sender_name: str = ""
    sender_address: str
    reply_to: str | None = None
    to: str = ""
    subject: str = ""
    received_at: datetime | None = None
    body: str = ""
    body_truncated: bool = False
    attachments: list[str] = Field(default_factory=list)
    is_automated: bool = False
    web_url: str | None = None

    @property
    def reply_address(self) -> str:
        return self.reply_to or self.sender_address

    @property
    def sender_display(self) -> str:
        if self.sender_name:
            return f"{self.sender_name} <{self.sender_address}>"
        return self.sender_address


# --- Structured output schema -------------------------------------------------------
# These models are sent to the LLM as a strict JSON schema. Every field is required;
# optional parts are nullable objects, so "task needed" and "task details" cannot disagree.


class Task(BaseModel):
    title: str = Field(description="Imperative and under 80 characters.")
    description: str = Field(
        description="Self-contained: who asks, what to do, key facts, amounts and links."
    )
    due_date: str | None = Field(
        description="YYYY-MM-DD only if the email states or clearly implies a deadline."
    )


class Reply(BaseModel):
    language: str = Field(description="ISO 639-1 code of the email's language, e.g. en, ru.")
    body: str = Field(description="Reply text only, no subject line.")


class Triage(BaseModel):
    summary: str = Field(description="One or two sentences.")
    category: Category
    priority: Priority
    risk: Risk
    risk_reason: str | None = Field(description="Why the risk is not 'none', else null.")
    task: Task | None = Field(description="Null unless the owner has something to do.")
    reply: Reply | None = Field(description="Null unless a person expects an answer.")


# --- Pipeline state --------------------------------------------------------------------


class MessageState(StrEnum):
    NEW = "new"  # waiting for triage
    AWAITING_APPROVAL = "awaiting_approval"  # review mode: a person decides
    ACTING = "acting"  # executing planned actions
    DONE = "done"
    REJECTED = "rejected"  # a person rejected the actions; the email is only marked processed
    DEAD = "dead"  # permanent error or too many attempts; needs attention


class ActionKind(StrEnum):
    NOTION_TASK = "notion_task"
    SHEETS_ROW = "sheets_row"
    GMAIL_DRAFT = "gmail_draft"
    MARK_PROCESSED = "mark_processed"


# Execution order. MARK_PROCESSED goes last: the label is the "commit" marker in Gmail.
ACTION_ORDER: tuple[ActionKind, ...] = (
    ActionKind.NOTION_TASK,
    ActionKind.SHEETS_ROW,
    ActionKind.GMAIL_DRAFT,
    ActionKind.MARK_PROCESSED,
)

# Actions with visible consequences; in review mode they wait for a person.
NEEDS_APPROVAL: frozenset[ActionKind] = frozenset({ActionKind.NOTION_TASK, ActionKind.GMAIL_DRAFT})


class ActionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"  # started; if the process dies here, the outcome is unknown
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Decision(StrEnum):
    AUTO = "auto"
    APPROVED = "approved"
    REJECTED = "rejected"


class ActionResult(BaseModel):
    external_id: str | None = None
    url: str | None = None
    preview: dict[str, Any] = Field(default_factory=dict)


class Overrides(BaseModel):
    """Edits a reviewer made before approving. The model's original output is kept."""

    reply_body: str | None = None
    task_title: str | None = None
    task_description: str | None = None
    skip: list[ActionKind] = Field(default_factory=list)

    def apply(self, triage: Triage) -> Triage:
        update: dict[str, Any] = {}
        if triage.task and (self.task_title or self.task_description):
            update["task"] = triage.task.model_copy(
                update={
                    "title": self.task_title or triage.task.title,
                    "description": self.task_description or triage.task.description,
                }
            )
        if triage.reply and self.reply_body:
            update["reply"] = triage.reply.model_copy(update={"body": self.reply_body})
        return triage.model_copy(update=update)


class Usage(BaseModel):
    provider: str
    model: str
    prompt_version: str
    input_tokens: int
    cached_tokens: int = 0
    output_tokens: int
    latency_ms: int
    cost_usd: float | None


class TriageOutcome(BaseModel):
    triage: Triage
    usage: Usage
