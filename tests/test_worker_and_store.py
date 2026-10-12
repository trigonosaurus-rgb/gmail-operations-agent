from pathlib import Path

from gmail_operations_agent.config import Settings
from gmail_operations_agent.domain import ActionKind, MessageState
from gmail_operations_agent.errors import BlockedError
from gmail_operations_agent.integrations.base import MarkProcessedSink
from gmail_operations_agent.pipeline import Pipeline, PipelineConfig
from gmail_operations_agent.rules import plan_actions
from gmail_operations_agent.store import Store
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
