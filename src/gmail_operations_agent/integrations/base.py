"""Interfaces between the pipeline and the outside world."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from gmail_operations_agent.domain import ActionKind, ActionResult, Email, Triage


@dataclass(frozen=True)
class RawMessage:
    id: str
    thread_id: str
    raw: bytes
    web_url: str | None = None


class MailSource(Protocol):
    name: str

    async def poll(self, is_known: Callable[[str], bool]) -> list[RawMessage]:
        """New messages, oldest first, skipping ids the store already has."""
        ...

    async def mark_processed(self, email: Email) -> ActionResult: ...


class ActionSink(Protocol):
    """One kind of side effect. Implementations must make retries safe:

    `find_existing` is called whenever an earlier attempt may have reached the remote
    service (the process died, or a timeout hid the response). If it returns a result,
    the pipeline records it instead of calling `execute` again.
    """

    kind: ActionKind

    def preview(self, email: Email, triage: Triage) -> dict[str, object]:
        """What `execute` would create, for review screens and the demo sandbox."""
        ...

    async def find_existing(self, email: Email) -> ActionResult | None: ...

    async def execute(self, email: Email, triage: Triage) -> ActionResult: ...


class MarkProcessedSink:
    """Wraps the source's 'processed' marker (a Gmail label) as the final action."""

    kind = ActionKind.MARK_PROCESSED

    def __init__(self, source: MailSource) -> None:
        self._source = source

    def preview(self, email: Email, triage: Triage) -> dict[str, object]:
        return {"source": self._source.name}

    async def find_existing(self, email: Email) -> ActionResult | None:
        return None  # adding a label twice is harmless

    async def execute(self, email: Email, triage: Triage) -> ActionResult:
        return await self._source.mark_processed(email)
