"""Settings from environment variables and `.env`, validated once at startup."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    openai_api_key: SecretStr | None = None
    llm_model: str = "gpt-6-luna"
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] | None = "low"
    llm_timeout_seconds: float = Field(60, gt=0)
    llm_daily_budget_usd: float = Field(1.0, ge=0)

    # Agent behaviour
    agent_mode: Literal["review", "auto"] = "review"
    agent_poll_seconds: int = Field(60, ge=5)
    agent_max_attempts: int = Field(8, ge=1)
    agent_concurrency: int = Field(3, ge=1, le=16)
    agent_lookback_days: int = Field(7, ge=1)
    agent_mark_as_read: bool = False
    agent_db_path: Path = Path("data/agent.sqlite3")
    agent_owner_context: str = "The owner did not describe themselves."
    agent_working_language: str = "English"
    agent_max_body_chars: int = Field(8000, ge=500)

    # Google
    google_credentials_file: Path = Path("credentials.json")
    google_token_file: Path = Path("token.json")
    gmail_processed_label: str = "Agent/Processed"
    google_sheets_id: str | None = None
    google_sheets_range: str = "Sheet1!A:J"

    # Notion
    notion_api_key: SecretStr | None = None
    notion_database_id: str | None = None
    notion_data_source_id: str | None = None
    notion_title_property: str = "Name"
    notion_priority_property: str | None = "Priority"
    notion_email_id_property: str | None = "Gmail ID"

    # Runtime
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    @property
    def notion_enabled(self) -> bool:
        return bool(self.notion_api_key and (self.notion_database_id or self.notion_data_source_id))

    @property
    def sheets_enabled(self) -> bool:
        return bool(self.google_sheets_id)

    @property
    def sheets_tab(self) -> str:
        return self.google_sheets_range.split("!", 1)[0]

    def problems_for_gmail(self) -> list[str]:
        """Human-readable reasons the Gmail worker cannot start."""
        problems = []
        if not self.openai_api_key:
            problems.append("OPENAI_API_KEY is not set.")
        if not self.google_token_file.exists():
            problems.append(f"{self.google_token_file} not found. Run `gmail-agent auth` first.")
        return problems
