"""Model configurations under comparison. Owner context is fixed so runs are comparable."""

from dataclasses import dataclass

OWNER_CONTEXT = (
    "Alex, a freelance AI engineer who builds chatbots, RAG assistants and automations "
    "for small businesses. Leads and client requests matter most."
)
TODAY = "2026-10-12"


@dataclass(frozen=True)
class Config:
    model: str
    effort: str | None


CONFIGS: dict[str, Config] = {
    "luna-none": Config("gpt-6-luna", "none"),
    "luna-low": Config("gpt-6-luna", "low"),
    "sol-low": Config("gpt-6.1-sol", "low"),
    "sol-medium": Config("gpt-6.1-sol", "medium"),
}
