"""Error taxonomy shared by every integration.

Each adapter (Gmail, Sheets, Notion, OpenAI) translates its vendor exceptions into
one of three kinds, so the pipeline can decide what to do without knowing vendors:

- TransientError: retry this message later with backoff.
- PermanentError: retrying will not help; move the message to the dead-letter state.
- BlockedError: a whole service is unusable (revoked token, exhausted quota, budget cap);
  pause processing and keep the message's attempts untouched.
"""


class AgentError(Exception):
    """Base class for errors the pipeline knows how to handle."""


class TransientError(AgentError):
    """Temporary failure such as a timeout, HTTP 429 or 5xx."""


class PermanentError(AgentError):
    """The same input will fail again, e.g. a validation error or a model refusal."""


class BlockedError(AgentError):
    """A service-wide problem that no single message can fix."""

    def __init__(self, service: str, reason: str) -> None:
        super().__init__(f"{service}: {reason}")
        self.service = service
        self.reason = reason


class ConfigError(Exception):
    """Invalid or missing configuration, reported before the worker starts."""
