"""Wiring: build the store, LLM, source, sinks, pipeline and worker from settings."""

import logging
from dataclasses import dataclass

from gmail_operations_agent.config import Settings
from gmail_operations_agent.errors import ConfigError
from gmail_operations_agent.integrations.base import ActionSink, MailSource, MarkProcessedSink
from gmail_operations_agent.integrations.gmail import GmailDraftSink, GmailSource
from gmail_operations_agent.integrations.google_api import GoogleApi
from gmail_operations_agent.integrations.google_auth import load_credentials, required_scopes
from gmail_operations_agent.integrations.notion import NotionSink
from gmail_operations_agent.integrations.sheets import SheetsSink
from gmail_operations_agent.llm.base import LLMProvider
from gmail_operations_agent.llm.openai_provider import OpenAIProvider
from gmail_operations_agent.pipeline import Pipeline, PipelineConfig
from gmail_operations_agent.store import Store
from gmail_operations_agent.worker import Worker

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings
    store: Store
    pipeline: Pipeline
    worker: Worker
    source: MailSource


def build_llm(settings: Settings) -> LLMProvider:
    if not settings.openai_api_key:
        raise ConfigError("OPENAI_API_KEY is not set.")
    return OpenAIProvider(
        settings.openai_api_key.get_secret_value(),
        settings.llm_model,
        reasoning_effort=settings.llm_reasoning_effort,
        timeout_seconds=settings.llm_timeout_seconds,
        owner_context=settings.agent_owner_context,
        working_language=settings.agent_working_language,
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
