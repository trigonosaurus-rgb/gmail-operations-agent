"""In-memory stand-ins for the LLM, mail source and action sinks. No network in tests."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from gmail_operations_agent.domain import (
    ActionKind,
    ActionResult,
    Category,
    Email,
    Priority,
    Reply,
    Risk,
    Task,
    Triage,
    TriageOutcome,
    Usage,
)
from gmail_operations_agent.integrations.base import RawMessage


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 12, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def make_email(id: str = "m1", **overrides: object) -> Email:
    values: dict[str, object] = {
        "id": id,
        "thread_id": f"t-{id}",
        "source": "fake",
        "message_id_header": f"<{id}@example.com>",
        "sender_name": "Anna Lee",
        "sender_address": "anna@acme.io",
        "subject": "Quote for a RAG chatbot",
        "body": "Could you send a quote by Friday?",
        "web_url": f"https://mail.google.com/mail/u/0/#all/t-{id}",
    }
    values.update(overrides)
    return Email.model_validate(values)


def make_triage(**overrides: object) -> Triage:
    values: dict[str, object] = {
        "summary": "Anna asks for a quote for a RAG chatbot by Friday.",
        "category": Category.LEAD,
        "priority": Priority.HIGH,
        "risk": Risk.NONE,
        "risk_reason": None,
        "task": Task(
            title="Send a quote to Anna", description="RAG chatbot, by Friday.", due_date=None
        ),
        "reply": Reply(language="en", body="Hi Anna, thanks! I'll send the quote by Thursday."),
    }
    values.update(overrides)
    return Triage.model_validate(values)


class FakeLLM:
    name = "fake"
    model = "fake-model"

    def __init__(self, *script: Triage | Exception) -> None:
        """Each call takes the next item; the last one repeats."""
        self.script = list(script) or [make_triage()]
        self.calls: list[str] = []

    async def triage(self, email: Email) -> TriageOutcome:
        self.calls.append(email.id)
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        usage = Usage(
            provider=self.name,
            model=self.model,
            prompt_version="test",
            input_tokens=1000,
            output_tokens=200,
            latency_ms=5,
            cost_usd=0.0002,
        )
        return TriageOutcome(triage=item, usage=usage)


class FakeSink:
    """Records calls. `failures` raises in order on execute; `remote` is what 'exists' remotely."""

    def __init__(self, kind: ActionKind, *failures: Exception) -> None:
        self.kind = kind
        self.failures = list(failures)
        self.executed: list[str] = []
        self.remote: dict[str, ActionResult] = {}
        self.lookups = 0
        self.on_execute: Callable[[Email], None] | None = None

    def preview(self, email: Email, triage: Triage) -> dict[str, object]:
        return {"kind": self.kind.value}

    async def find_existing(self, email: Email) -> ActionResult | None:
        self.lookups += 1
        return self.remote.get(email.id)

    async def execute(self, email: Email, triage: Triage) -> ActionResult:
        if self.on_execute:
            self.on_execute(email)
        if self.failures:
            raise self.failures.pop(0)
        self.executed.append(email.id)
        result = ActionResult(external_id=f"{self.kind.value}-{email.id}")
        self.remote[email.id] = result
        return result


class FakeSource:
    name = "fake"

    def __init__(self, *messages: RawMessage) -> None:
        self.messages = list(messages)
        self.processed: list[str] = []

    async def poll(self, is_known: Callable[[str], bool]) -> list[RawMessage]:
        return [m for m in self.messages if not is_known(m.id)]

    async def mark_processed(self, email: Email) -> ActionResult:
        self.processed.append(email.id)
        return ActionResult(external_id="label")
