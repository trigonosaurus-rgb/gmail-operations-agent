"""Wiring: build the store, LLM, source, sinks, pipeline and worker from settings."""

import logging
import secrets
from dataclasses import dataclass

from gmail_operations_agent.config import Settings
from gmail_operations_agent.demo import data as demo_data
from gmail_operations_agent.demo.llm import DemoLLM
from gmail_operations_agent.demo.sandbox import DemoSource, SandboxSink
from gmail_operations_agent.demo.service import SCENARIO_DELAY_SECONDS, DemoLimits, DemoService
from gmail_operations_agent.domain import ActionKind, Email
from gmail_operations_agent.errors import ConfigError
from gmail_operations_agent.integrations.base import ActionSink, MailSource, MarkProcessedSink
from gmail_operations_agent.integrations.gmail import GmailDraftSink, GmailSource, draft_preview
from gmail_operations_agent.integrations.google_api import GoogleApi
from gmail_operations_agent.integrations.google_auth import load_credentials, required_scopes
from gmail_operations_agent.integrations.notion import NotionSink, task_preview
from gmail_operations_agent.integrations.sheets import SheetsSink, row_preview
from gmail_operations_agent.llm.base import LLMProvider
from gmail_operations_agent.llm.openai_provider import OpenAIProvider
from gmail_operations_agent.pipeline import Pipeline, PipelineConfig
from gmail_operations_agent.store import Clock, Store, utcnow
from gmail_operations_agent.worker import Worker

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings
    store: Store
    pipeline: Pipeline
    worker: Worker
    source: MailSource
    demo: DemoService | None = None


def build_llm(
    settings: Settings, owner_context: str | None = None, working_language: str | None = None
) -> LLMProvider:
    if not settings.openai_api_key:
        raise ConfigError("OPENAI_API_KEY is not set.")
    return OpenAIProvider(
        settings.openai_api_key.get_secret_value(),
        settings.llm_model,
        reasoning_effort=settings.llm_reasoning_effort,
        timeout_seconds=settings.llm_timeout_seconds,
        owner_context=owner_context or settings.agent_owner_context,
        working_language=working_language or settings.agent_working_language,
    )


def pipeline_config(settings: Settings) -> PipelineConfig:
    return PipelineConfig(
        mode=settings.agent_mode,
        max_attempts=settings.agent_max_attempts,
        max_body_chars=settings.agent_max_body_chars,
        daily_budget_usd=settings.llm_daily_budget_usd or None,
    )


def build_gmail_runtime(settings: Settings) -> Runtime:
    creds = load_credentials(settings.google_token_file, required_scopes(settings.sheets_enabled))
    api = GoogleApi(creds)
    source = GmailSource(
        api,
        settings.gmail_processed_label,
        lookback_days=settings.agent_lookback_days,
        mark_as_read=settings.agent_mark_as_read,
    )
    sinks: list[ActionSink] = [GmailDraftSink(api), MarkProcessedSink(source)]
    if settings.sheets_enabled and settings.google_sheets_id:
        sinks.append(SheetsSink(api, settings.google_sheets_id, settings.sheets_tab))
    if settings.notion_enabled and settings.notion_api_key:
        sinks.append(
            NotionSink(
                settings.notion_api_key.get_secret_value(),
                database_id=settings.notion_database_id,
                data_source_id=settings.notion_data_source_id,
                title_property=settings.notion_title_property,
                priority_property=settings.notion_priority_property,
                email_id_property=settings.notion_email_id_property,
            )
        )
    logger.info(
        "Actions enabled: %s; mode: %s; model: %s",
        ", ".join(sorted(sink.kind.value for sink in sinks)),
        settings.agent_mode,
        settings.llm_model,
    )
    store = Store(settings.agent_db_path)
    pipeline = Pipeline(store, build_llm(settings), sinks, pipeline_config(settings))
    worker = Worker(
        pipeline,
        source,
        poll_seconds=settings.agent_poll_seconds,
        concurrency=settings.agent_concurrency,
    )
    return Runtime(settings, store, pipeline, worker, source)


def build_demo_runtime(
    settings: Settings,
    store: Store | None = None,
    live: LLMProvider | None = None,
    clock: Clock = utcnow,
) -> Runtime:
    """The public demo: seeded sandboxes, replayed or live triage, no external side effects.

    `live` defaults to OpenAI when a key is set; tests pass a fake and a fake clock.
    """
    data = demo_data.load()
    store = store or Store(settings.demo_db_path, clock=clock)
    limits = DemoLimits(
        daily_quota=settings.demo_daily_quota,
        monthly_budget_usd=settings.demo_monthly_budget_usd,
        sandbox_ttl_hours=settings.demo_sandbox_ttl_hours,
        max_sandboxes=settings.demo_max_sandboxes,
        sandboxes_per_visitor=settings.demo_sandboxes_per_visitor,
        max_body_chars=settings.agent_max_body_chars,
    )
    if live is None and settings.openai_api_key:
        # The recordings were made for this owner; live calls use the same context.
        live = build_llm(settings, data.owner_context, data.working_language)
    if settings.demo_secret:
        secret = settings.demo_secret.get_secret_value().encode()
    else:
        logger.warning("DEMO_SECRET is not set: using a random one, quotas reset on restart")
        secret = secrets.token_bytes(32)

    # The service and the sinks need each other (failure hook, wake-up); bind late.
    holder: dict[str, DemoService] = {}

    def has_budget() -> bool:
        return holder["service"].has_budget()

    def fail(kind: ActionKind, email: Email) -> str | None:
        return holder["service"].sandbox_failure(kind, email)

    llm = DemoLLM(data.recordings, live, has_budget, settings.demo_replay_speed)
    source = DemoSource()
    sinks: list[ActionSink] = [
        SandboxSink(ActionKind.NOTION_TASK, lambda e, t: task_preview(t), fail),
        SandboxSink(ActionKind.SHEETS_ROW, row_preview, fail),
        SandboxSink(ActionKind.GMAIL_DRAFT, draft_preview, fail),
        MarkProcessedSink(source),
    ]
    config = PipelineConfig(
        mode="review",
        max_attempts=3,
        retry_base_seconds=10,
        max_body_chars=settings.agent_max_body_chars,
        daily_budget_usd=None,  # the demo caps live spend per month, in DemoLLM
    )
    pipeline = Pipeline(store, llm, sinks, config, clock=clock)
    # Replays mostly wait, so the demo can run many at once.
    worker = Worker(pipeline, source, poll_seconds=60, concurrency=12, clock=clock)
    service = DemoService(
        store,
        pipeline,
        llm,
        data,
        limits,
        secret,
        worker.wake,
        clock=clock,
        scenario_delay=SCENARIO_DELAY_SECONDS * settings.demo_replay_speed,
    )
    holder["service"] = service
    logger.info("Demo mode; live model: %s", "on" if live else "off (recorded runs only)")
    return Runtime(settings, store, pipeline, worker, source, demo=service)
