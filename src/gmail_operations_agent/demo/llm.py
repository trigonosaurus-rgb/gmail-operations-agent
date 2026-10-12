"""The demo's LLM: replays recorded outputs when it can, calls the live model otherwise."""

import asyncio
from collections.abc import Callable

from gmail_operations_agent.demo.data import Recording, fingerprint
from gmail_operations_agent.domain import Email, TriageOutcome
from gmail_operations_agent.errors import BlockedError, PermanentError
from gmail_operations_agent.llm.base import LLMProvider

REPLAY_PROVIDER = "replay"


class DemoLLM:
    name = "demo"

    def __init__(
        self,
        recordings: dict[str, Recording],
        live: LLMProvider | None,
        has_budget: Callable[[], bool],
        replay_speed: float = 1.0,
    ) -> None:
        self._recordings = recordings
        self._live = live
        self._has_budget = has_budget
        self._replay_speed = replay_speed
        self.model = live.model if live else "gpt-6-luna"

    def can_replay(self, email: Email) -> bool:
        return fingerprint(email) in self._recordings

    def live_available(self) -> bool:
        return self._live is not None and self._has_budget()

    async def triage(self, email: Email) -> TriageOutcome:
        recording = self._recordings.get(fingerprint(email))
        if recording:
            # Wait as long as the original call took, so the inbox fills in like the real thing.
            await asyncio.sleep(recording.usage.latency_ms / 1000 * self._replay_speed)
            usage = recording.usage.model_copy(update={"provider": REPLAY_PROVIDER})
            return TriageOutcome(triage=recording.triage, usage=usage)
        if self._live is None:
            raise PermanentError("the live model is off in this demo; pick a preset")
        if not self._has_budget():
            raise PermanentError("the demo's monthly LLM budget is used up; pick a preset")
        try:
            return await self._live.triage(email)
        except BlockedError as exc:
            # In the shared demo, one visitor's failed call must not pause everyone's inbox.
            raise PermanentError(f"live model unavailable: {exc.reason}") from exc
