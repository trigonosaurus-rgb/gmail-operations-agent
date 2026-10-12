import asyncio
import sqlite3
from pathlib import Path

from gmail_operations_agent.config import Settings
from gmail_operations_agent.domain import ActionKind, MessageState
from gmail_operations_agent.errors import BlockedError
from gmail_operations_agent.integrations.base import MarkProcessedSink
from gmail_operations_agent.pipeline import Pipeline, PipelineConfig
from gmail_operations_agent.rules import plan_actions
from gmail_operations_agent.store import MIGRATIONS, Store
from gmail_operations_agent.worker import BLOCKED_PAUSE_SECONDS, Worker
from tests.fakes import FakeClock, FakeLLM, FakeSink, FakeSource, make_email, make_triage


def build(store: Store, clock: FakeClock, llm: FakeLLM) -> tuple[Worker, FakeSource]:
    source = FakeSource()
    pipeline = Pipeline(
        store,
        llm,
        [FakeSink(ActionKind.SHEETS_ROW), MarkProcessedSink(source)],
        PipelineConfig(mode="auto"),
        clock=clock,
    )
    return Worker(pipeline, source, poll_seconds=60, clock=clock), source


async def test_worker_processes_due_messages(store: Store, clock: FakeClock) -> None:
    worker, source = build(store, clock, FakeLLM())
    worker.pipeline.add_email(make_email("a"))
    worker.pipeline.add_email(make_email("b"))
    assert await worker.tick() == 60
    assert sorted(source.processed) == ["a", "b"]
    assert worker.status.processed_total == 2


async def test_worker_pauses_when_a_service_is_blocked(store: Store, clock: FakeClock) -> None:
    worker, _ = build(store, clock, FakeLLM(BlockedError("openai", "quota exhausted")))
    worker.pipeline.add_email(make_email("a"))
    assert await worker.tick() == BLOCKED_PAUSE_SECONDS
    assert worker.status.blocked_service == "openai"
    record = store.get_message("a")
    assert record is not None
    assert record.attempts == 0


async def test_worker_wakes_up_for_a_retry_due_before_the_next_poll(
    store: Store, clock: FakeClock
) -> None:
    from gmail_operations_agent.errors import TransientError

    worker, _ = build(store, clock, FakeLLM(TransientError("timeout")))
    worker.pipeline.config = PipelineConfig(mode="auto", retry_base_seconds=10)
    worker.pipeline.add_email(make_email("a"))
    delay = await worker.tick()
    assert 8 <= delay <= 12  # the retry backoff, not the 60 s poll interval


async def test_a_wake_during_a_cycle_is_not_lost(store: Store, clock: FakeClock) -> None:
    """An approval that lands while a cycle runs must start another cycle, not wait for the poll.

    The cycle may already have seen that message (as awaiting approval), so only a new
    cycle picks it up. Under load, this lost wake-up left approved mail "Running" for 60 s.
    """
    worker, _ = build(store, clock, FakeLLM())
    ticks = 0
    tick = worker.tick

    async def tick_with_an_approval_meanwhile() -> float:
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            worker.wake()
        return await tick()

    worker.tick = tick_with_an_approval_meanwhile  # type: ignore[method-assign]
    stop = asyncio.Event()
    task = asyncio.create_task(worker.run(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await task
    assert ticks >= 2


def test_store_migrations_are_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "agent.sqlite3"
    first = Store(path)
    first.add_message(make_email("a"))
    first.close()
    second = Store(path)  # reopening must not re-run migrations or lose data
    record = second.get_message("a")
    assert record is not None
    assert record.state == MessageState.NEW
    second.close()


def test_upgrade_from_the_first_schema_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "agent.sqlite3"
    db = sqlite3.connect(path)
    for statement in MIGRATIONS[0].split(";"):
        if statement.strip():
            db.execute(statement)
    db.execute(
        "INSERT INTO messages (id, source, state, email_json, created_at, updated_at)"
        " VALUES ('old', 'gmail', 'done', ?, ?, ?)",
        (
            make_email("old").model_dump_json(),
            "2026-10-01T00:00:00.000000+00:00",
            "2026-10-01T00:00:00.000000+00:00",
        ),
    )
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()

    store = Store(path)
    record = store.get_message("old")
    assert record is not None
    assert record.owner == ""
    assert [r.id for r in store.list_messages()] == ["old"]
    store.close()


def test_message_timestamps_never_tie(store: Store) -> None:
    # The fake clock stands still, like a coarse system clock during a burst of inserts.
    for name in "abc":
        store.add_message(make_email(name))
    stamps = [r.created_at for r in store.list_messages()]
    assert len(set(stamps)) == 3
    assert [r.id for r in store.list_messages()] == ["c", "b", "a"]


def test_plan_actions_respects_triage_and_configuration() -> None:
    every = set(ActionKind)
    assert plan_actions(make_triage(), every) == list(ActionKind)
    assert plan_actions(make_triage(task=None, reply=None), every) == [
        ActionKind.SHEETS_ROW,
        ActionKind.MARK_PROCESSED,
    ]
    assert plan_actions(make_triage(), {ActionKind.MARK_PROCESSED}) == [ActionKind.MARK_PROCESSED]


def test_settings_report_what_is_missing(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        openai_api_key=None,
        google_token_file=tmp_path / "missing.json",
    )
    problems = settings.problems_for_gmail()
    assert any("OPENAI_API_KEY" in p for p in problems)
    assert any("gmail-agent auth" in p for p in problems)
    assert not settings.notion_enabled
