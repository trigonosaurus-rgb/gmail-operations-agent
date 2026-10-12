from typing import Protocol

from gmail_operations_agent.domain import Email, TriageOutcome


class LLMProvider(Protocol):
    """Anything that can triage an email. Implementations map vendor errors to errors.py."""

    name: str
    model: str

    async def triage(self, email: Email) -> TriageOutcome: ...
