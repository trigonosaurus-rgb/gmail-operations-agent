"""OpenAI implementation of LLMProvider: Responses API with a strict Pydantic schema."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import openai
from openai import AsyncOpenAI
from pydantic import ValidationError

from gmail_operations_agent.domain import Email, Triage, TriageOutcome, Usage
from gmail_operations_agent.errors import AgentError, BlockedError, PermanentError, TransientError
from gmail_operations_agent.llm.pricing import cost_usd
from gmail_operations_agent.llm.prompt import Prompt, format_email, load_prompt

logger = logging.getLogger(__name__)


def _today() -> date:
    return datetime.now(UTC).date()


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        reasoning_effort: str | None = "low",
        timeout_seconds: float = 60,
        owner_context: str = "",
        working_language: str = "English",
        prompt: Prompt | None = None,
        today: Callable[[], date] = _today,
        client: AsyncOpenAI | None = None,
    ) -> None:
        # The SDK already retries connection errors, 429 and 5xx twice with backoff;
        # anything that survives that becomes a pipeline-level retry.
        self._client = client or AsyncOpenAI(
            api_key=api_key, timeout=timeout_seconds, max_retries=2
        )
        self.model = model
        self._effort = reasoning_effort
        self._owner_context = owner_context
        self._working_language = working_language
        self._prompt = prompt or load_prompt("triage")
        self._today = today

    @property
    def prompt_version(self) -> str:
        return self._prompt.version

    async def triage(self, email: Email) -> TriageOutcome:
        instructions = self._prompt.render(
            owner_context=self._owner_context,
            today=self._today().isoformat(),
            working_language=self._working_language,
        )
        extra: dict[str, Any] = {}
        if self._effort:
            extra["reasoning"] = {"effort": self._effort}
        started = time.perf_counter()
        try:
            response = await self._client.responses.parse(
                model=self.model,
                instructions=instructions,
                input=format_email(email),
                text_format=Triage,
                store=False,  # do not keep email content on the provider side
                max_output_tokens=4000,
                **extra,
            )
        except openai.OpenAIError as exc:
            raise classify_openai_error(exc, self.model) from exc
        except ValidationError as exc:
            raise PermanentError(f"model output does not match the schema: {exc}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000)

        parsed = response.output_parsed
        if parsed is None:
            raise PermanentError(_explain_missing_output(response))

        usage = response.usage
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
        details = usage.input_tokens_details if usage else None
        cached = (details.cached_tokens or 0) if details else 0
        return TriageOutcome(
            triage=parsed,
            usage=Usage(
                provider=self.name,
                model=self.model,
                prompt_version=self._prompt.version,
                input_tokens=input_tokens,
                cached_tokens=cached,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_usd=cost_usd(self.model, input_tokens, cached, output_tokens),
            ),
        )


def _explain_missing_output(response: Any) -> str:
    for item in getattr(response, "output", None) or []:
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                return f"model refused: {content.refusal}"
    incomplete = getattr(response, "incomplete_details", None)
    if incomplete is not None:
        return f"model output incomplete: {incomplete.reason}"
    return f"model returned no structured output (status {getattr(response, 'status', '?')})"


def classify_openai_error(exc: openai.OpenAIError, model: str) -> AgentError:
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return BlockedError("openai", "the API key was rejected or has no access to the model")
    if isinstance(exc, openai.RateLimitError):
        if getattr(exc, "code", None) == "insufficient_quota":
            return BlockedError("openai", "quota exhausted: top up the API balance")
        return TransientError(f"OpenAI rate limit: {exc}")
    if isinstance(exc, openai.NotFoundError):
        return BlockedError("openai", f"model {model!r} not found")
    if isinstance(exc, openai.APIConnectionError | openai.InternalServerError):
        return TransientError(f"OpenAI unavailable: {exc}")
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return TransientError(f"OpenAI server error {exc.status_code}")
    if isinstance(exc, openai.LengthFinishReasonError | openai.ContentFilterFinishReasonError):
        return PermanentError(f"model output unusable: {exc}")
    return PermanentError(f"OpenAI request failed: {exc}")
