"""Stand-ins for Gmail, Notion and Sheets: they record what would be created and touch nothing."""

from collections.abc import Callable

from gmail_operations_agent.domain import ActionKind, ActionResult, Email, Triage
from gmail_operations_agent.errors import PermanentError
from gmail_operations_agent.integrations.base import RawMessage

Preview = Callable[[Email, Triage], dict[str, object]]
FailureHook = Callable[[ActionKind, Email], str | None]

PROCESSED_LABEL = "Agent/Processed"


class SandboxSink:
    """Runs instantly and stores the preview as the result, so the UI shows the would-be output."""

    def __init__(self, kind: ActionKind, preview: Preview, fail: FailureHook) -> None:
        self.kind = kind
        self._preview = preview
        self._fail = fail

    def preview(self, email: Email, triage: Triage) -> dict[str, object]:
        return self._preview(email, triage)

    async def find_existing(self, email: Email) -> ActionResult | None:
        return None  # nothing leaves the process, so an earlier attempt left nothing behind

    async def execute(self, email: Email, triage: Triage) -> ActionResult:
        error = self._fail(self.kind, email)
        if error:
            raise PermanentError(error)
        return ActionResult(
            external_id=f"sandbox:{self.kind.value}:{email.id}",
            preview=self._preview(email, triage),
        )


class DemoSource:
    """Demo mail arrives through the API, not by polling."""

    name = "demo"

    async def poll(self, is_known: Callable[[str], bool]) -> list[RawMessage]:
        return []

    async def mark_processed(self, email: Email) -> ActionResult:
        return ActionResult(
            external_id="sandbox:label", preview={"label": PROCESSED_LABEL, "marked_read": False}
        )
