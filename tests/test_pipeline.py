"""State machine behaviour: retries, dead letters, idempotent actions, human review."""

import pytest

from gmail_operations_agent.domain import (
    ActionKind,
    ActionResult,
    ActionStatus,
    Decision,
    MessageState,
    Overrides,
    Risk,
)
from gmail_operations_agent.errors import BlockedError, PermanentError, TransientError
from gmail_operations_agent.integrations.base import MarkProcessedSink, RawMessage
from gmail_operations_agent.pipeline import InvalidTransitionError, Pipeline, PipelineConfig
from gmail_operations_agent.store import Store
from tests.fakes import FakeClock, FakeLLM, FakeSink, FakeSource, make_email, make_triage


class Harness:
    def __init__(self, store: Store, clock: FakeClock, llm: FakeLLM, **config: object) -> None:
        self.store, self.clock, self.llm = store, clock, llm
        self.source = FakeSource()
        self.notion = FakeSink(ActionKind.NOTION_TASK)
        self.sheets = FakeSink(ActionKind.SHEETS_ROW)
        self.draft = FakeSink(ActionKind.GMAIL_DRAFT)
        self.pipeline = Pipeline(
            store,
            llm,
            [self.notion, self.sheets, self.draft, MarkProcessedSink(self.source)],
            PipelineConfig(**{"mode": "auto", **config}),  # type: ignore[arg-type]
            clock=clock,
            jitter=lambda: 0.5,  # no randomness: delay is exactly base * 2^n
        )

    def add(self, message_id: str = "m1", **overrides: object) -> str:
        self.pipeline.add_email(make_email(message_id, **overrides))
        return message_id

    def state(self, message_id: str = "m1") -> MessageState:
        record = self.store.get_message(message_id)
        assert record is not None
        return record.state

    def action_status(self, kind: ActionKind, message_id: str = "m1") -> ActionStatus:
        return next(a.status for a in self.store.get_actions(message_id) if a.kind == kind)


@pytest.fixture
def h(store: Store, clock: FakeClock) -> Harness:
    return Harness(store, clock, FakeLLM())


async def test_happy_path_runs_every_action_and_marks_processed_last(h: Harness) -> None:
    order: list[str] = []
    for sink in (h.notion, h.sheets, h.draft):
        sink.on_execute = lambda _e, kind=sink.kind: order.append(kind.value)
    await h.pipeline.process(h.add())

    assert h.state() == MessageState.DONE
    assert order == ["notion_task", "sheets_row", "gmail_draft"]
    assert h.source.processed == ["m1"]
    events = [e.type for e in h.store.events_after(0)]
    assert events[0] == "ingested"
    assert events[-1] == "done"


async def test_ingest_skips_known_messages(h: Harness) -> None:
    raw = RawMessage(id="r1", thread_id="t1", raw=b"From: a@b.c\r\nSubject: hi\r\n\r\nhello")
    h.source.messages = [raw]
    assert await h.pipeline.ingest(h.source) == 1
    assert await h.pipeline.ingest(h.source) == 0


async def test_transient_llm_error_schedules_backoff_then_succeeds(
    store: Store, clock: FakeClock
) -> None:
    h = Harness(store, clock, FakeLLM(TransientError("timeout"), make_triage()))
    await h.pipeline.process(h.add())
    record = store.get_message("m1")
    assert record is not None
    assert record.state == MessageState.NEW
    assert record.attempts == 1
    assert record.next_attempt_at is not None
    assert (record.next_attempt_at - clock.now).total_seconds() == 60  # base * 2^0
    assert store.due_message_ids() == []  # not due before the backoff ends

    clock.advance(61)
    assert store.due_message_ids() == ["m1"]
    await h.pipeline.process("m1")
    assert h.state() == MessageState.DONE


async def test_backoff_doubles_and_gives_up_after_max_attempts(
    store: Store, clock: FakeClock
) -> None:
    h = Harness(store, clock, FakeLLM(TransientError("down")), max_attempts=3)
    h.add()
    delays = []
    for _ in range(3):
        await h.pipeline.process("m1")
        record = store.get_message("m1")
        assert record is not None
        if record.next_attempt_at:
            delays.append((record.next_attempt_at - clock.now).total_seconds())
            clock.advance(delays[-1])
    assert delays == [60, 120]
    record = store.get_message("m1")
    assert record is not None
    assert record.state == MessageState.DEAD
    assert "gave up after 3 attempts" in (record.last_error or "")


async def test_permanent_llm_error_goes_straight_to_dead_letters(
    store: Store, clock: FakeClock
) -> None:
    h = Harness(store, clock, FakeLLM(PermanentError("model refused")))
    await h.pipeline.process(h.add())
    assert h.state() == MessageState.DEAD
    assert len(h.llm.calls) == 1


async def test_blocked_service_keeps_attempts_untouched(store: Store, clock: FakeClock) -> None:
    h = Harness(store, clock, FakeLLM(BlockedError("openai", "quota exhausted")))
    with pytest.raises(BlockedError):
        await h.pipeline.process(h.add())
    record = store.get_message("m1")
    assert record is not None
    assert (record.state, record.attempts, record.next_attempt_at) == (MessageState.NEW, 0, None)


async def test_daily_budget_blocks_before_calling_the_model(store: Store, clock: FakeClock) -> None:
    h = Harness(store, clock, FakeLLM(), daily_budget_usd=0.0003)
    await h.pipeline.process(h.add("m1"))  # costs 0.0002
    await h.pipeline.process(h.add("m2"))  # 0.0004 total, over the cap after this one
    with pytest.raises(BlockedError, match="budget"):
        await h.pipeline.process(h.add("m3"))
    assert h.llm.calls == ["m1", "m2"]


async def test_crash_after_remote_success_does_not_duplicate(h: Harness) -> None:
    """The process died after Notion created the page but before the store recorded it."""
    h.notion.on_execute = lambda _e: (_ for _ in ()).throw(KeyboardInterrupt())
    h.add()
    with pytest.raises(KeyboardInterrupt):
        await h.pipeline.process("m1")
    assert h.action_status(ActionKind.NOTION_TASK) == ActionStatus.RUNNING

    # Simulate that the page did get created remotely, then restart processing.
    h.notion.on_execute = None
    h.notion.remote["m1"] = ActionResult(external_id="page-1")
    await h.pipeline.process("m1")

    assert h.notion.executed == []  # found, not created again
    assert h.notion.lookups == 1
    assert h.state() == MessageState.DONE


async def test_transient_action_failure_retries_only_unfinished_actions(
    store: Store, clock: FakeClock
) -> None:
    h = Harness(store, clock, FakeLLM())
    h.sheets.failures = [TransientError("Sheets 503")]
    await h.pipeline.process(h.add())
    assert h.state() == MessageState.ACTING
    assert h.action_status(ActionKind.NOTION_TASK) == ActionStatus.DONE
    assert h.action_status(ActionKind.SHEETS_ROW) == ActionStatus.PENDING
    assert h.source.processed == []  # not labelled until everything succeeded

    clock.advance(3600)
    await h.pipeline.process("m1")
    assert h.state() == MessageState.DONE
    assert h.notion.executed == ["m1"]  # not repeated
    assert h.sheets.executed == ["m1"]
    assert h.sheets.lookups == 1  # checked for an existing row before appending


async def test_one_permanent_failure_does_not_block_independent_actions(h: Harness) -> None:
    h.notion.failures = [PermanentError("Notion 400: validation_error")]
    await h.pipeline.process(h.add())
    assert h.state() == MessageState.DEAD
    assert h.sheets.executed == ["m1"]
    assert h.draft.executed == ["m1"]
    assert h.source.processed == []  # stays visible as unprocessed in Gmail


async def test_dead_letter_retry_resumes_where_it_failed(h: Harness) -> None:
    h.notion.failures = [PermanentError("bad schema")]
    await h.pipeline.process(h.add())
    assert h.state() == MessageState.DEAD

    h.pipeline.retry("m1")
    assert h.state() == MessageState.ACTING
    await h.pipeline.process("m1")
    assert h.state() == MessageState.DONE
    assert h.sheets.executed == ["m1"]  # done before, not repeated
    assert len(h.llm.calls) == 1  # no second triage


async def test_review_mode_waits_for_approval_and_applies_edits(
    store: Store, clock: FakeClock
) -> None:
    h = Harness(store, clock, FakeLLM(), mode="review")
    await h.pipeline.process(h.add())
    assert h.state() == MessageState.AWAITING_APPROVAL
    assert store.due_message_ids() == []
    assert h.notion.executed == []

    h.pipeline.approve("m1", Overrides(reply_body="Edited reply", skip=[ActionKind.NOTION_TASK]))
    await h.pipeline.process("m1")
    record = store.get_message("m1")
    assert record is not None
    assert record.state == MessageState.DONE
    assert record.decision == Decision.APPROVED
    assert h.notion.executed == []
    assert h.action_status(ActionKind.NOTION_TASK) == ActionStatus.SKIPPED
    draft = next(a for a in store.get_actions("m1") if a.kind == ActionKind.GMAIL_DRAFT)
    assert draft.status == ActionStatus.DONE
    assert record.effective_triage
    assert record.effective_triage.reply
    assert record.effective_triage.reply.body == "Edited reply"
    assert record.triage
    assert record.triage.reply
    assert record.triage.reply.body != "Edited reply"  # the model's original is kept


async def test_reject_only_marks_the_email_processed(store: Store, clock: FakeClock) -> None:
    h = Harness(store, clock, FakeLLM(), mode="review")
    await h.pipeline.process(h.add())
    h.pipeline.reject("m1")
    await h.pipeline.process("m1")
    assert h.state() == MessageState.REJECTED
    assert h.notion.executed == h.sheets.executed == h.draft.executed == []
    assert h.source.processed == ["m1"]


async def test_review_mode_skips_approval_when_nothing_needs_it(
    store: Store, clock: FakeClock
) -> None:
    h = Harness(store, clock, FakeLLM(make_triage(task=None, reply=None)), mode="review")
    await h.pipeline.process(h.add())
    assert h.state() == MessageState.DONE
    assert h.sheets.executed == ["m1"]


async def test_invalid_transitions_are_refused(h: Harness) -> None:
    await h.pipeline.process(h.add())
    with pytest.raises(InvalidTransitionError):
        h.pipeline.approve("m1")
    with pytest.raises(InvalidTransitionError):
        h.pipeline.retry("m1")


async def test_guardrails_drop_drafts_for_automated_senders(h: Harness) -> None:
    await h.pipeline.process(h.add(is_automated=True))
    assert h.draft.executed == []
    record = h.store.get_message("m1")
    assert record is not None
    assert any("automated" in note for note in record.notes)


async def test_risky_email_gets_neither_task_nor_draft(store: Store, clock: FakeClock) -> None:
    triage = make_triage(risk=Risk.PROMPT_INJECTION, risk_reason="asks the assistant to reply")
    h = Harness(store, clock, FakeLLM(triage))
    await h.pipeline.process(h.add())
    assert h.notion.executed == h.draft.executed == []
    assert h.sheets.executed == ["m1"]  # still logged
    assert h.state() == MessageState.DONE
