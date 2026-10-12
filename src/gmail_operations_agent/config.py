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

    # API server
    api_host: str = "127.0.0.1"
    api_port: int = Field(8000, ge=1, le=65535)
    # The Gmail mode has no login: it refuses to listen beyond this machine unless allowed.
    api_allow_remote: bool = False
    # Proxies trusted to set X-Forwarded-For (the demo's quota is per client address).
    api_forwarded_allow_ips: str = "127.0.0.1"
    web_dist_dir: Path = Path("frontend/dist")

    # Public demo (`gmail-agent demo`): synthetic inbox, sandboxed actions
    demo_db_path: Path = Path("data/demo.sqlite3")
    # Salt for hashing visitor addresses; a random one is used if unset (quotas reset on restart).
    demo_secret: SecretStr | None = None
    demo_daily_quota: int = Field(5, ge=0)
    # Live LLM spend cap per calendar month; past it, only the recorded presets work.
    demo_monthly_budget_usd: float = Field(5.0, ge=0)
    demo_sandbox_ttl_hours: float = Field(24, gt=0)
    demo_max_sandboxes: int = Field(500, ge=1)
    demo_sandboxes_per_visitor: int = Field(20, ge=1)
    # Recorded triage replays wait this share of the original latency (0 = instant).
    demo_replay_speed: float = Field(1.0, ge=0, le=1)

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
