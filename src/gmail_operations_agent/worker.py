"""The polling loop: ingest new mail, process due messages with bounded concurrency."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from gmail_operations_agent.errors import BlockedError, TransientError
from gmail_operations_agent.integrations.base import MailSource
from gmail_operations_agent.pipeline import Pipeline
from gmail_operations_agent.store import Clock, utcnow

logger = logging.getLogger(__name__)

BLOCKED_PAUSE_SECONDS = 300


@dataclass
class WorkerStatus:
    running: bool = False
    last_poll_at: datetime | None = None
    last_error: str | None = None
    blocked_service: str | None = None
    blocked_reason: str | None = None
    blocked_until: datetime | None = None
    processed_total: int = 0
    in_flight: set[str] = field(default_factory=set)


class Worker:
    def __init__(
        self,
        pipeline: Pipeline,
        source: MailSource,
        poll_seconds: float = 60,
        concurrency: int = 3,
        clock: Clock = utcnow,
    ) -> None:
        self.pipeline = pipeline
        self.source = source
        self.status = WorkerStatus()
        self._poll_seconds = poll_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._wake = asyncio.Event()
        self._clock = clock

    def wake(self) -> None:
        """Process now instead of waiting for the next poll (e.g. after an approval)."""
        self._wake.set()

    async def run(self, stop: asyncio.Event) -> None:
        self.status.running = True
        logger.info("Worker started (source: %s)", self.source.name)
        try:
            while not stop.is_set():
                # Cleared before the cycle, not after: a wake() that arrives while the
                # cycle runs (an approval of mail it already passed) starts the next one.
                self._wake.clear()
                delay = await self.tick()
                await _wait_any(stop, self._wake, delay)
        finally:
            self.status.running = False
            logger.info("Worker stopped")

    async def tick(self) -> float:
        """One cycle. Returns how long to sleep before the next one."""
        try:
            added = await self.pipeline.ingest(self.source)
            self.status.last_poll_at = self._clock()
            if added:
                logger.info("Ingested %d new message(s)", added)
            await self.drain()
        except BlockedError as exc:
            return self._blocked(exc)
        except TransientError as exc:
            self.status.last_error = str(exc)
            logger.warning("Poll failed, will retry: %s", exc)
            return self._poll_seconds
        except Exception as exc:
            self.status.last_error = repr(exc)
            logger.exception("Worker cycle failed")
            return self._poll_seconds
        self.status.last_error = None
        self.status.blocked_service = self.status.blocked_reason = None
        self.status.blocked_until = None
        return self._next_delay()

    async def drain(self) -> None:
        """Process every message that is due now; stop early if a service is blocked."""
        seen: set[str] = set()
        while True:
            due = [
                mid
                for mid in self.pipeline.store.due_message_ids(limit=50)
                if mid not in self.status.in_flight and mid not in seen
            ]
            if not due:
                return
            seen.update(due)
            results = await asyncio.gather(
                *(self._process_one(mid) for mid in due), return_exceptions=True
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result

    async def _process_one(self, message_id: str) -> None:
        async with self._semaphore:
            self.status.in_flight.add(message_id)
            try:
                await self.pipeline.process(message_id)
                self.status.processed_total += 1
            finally:
                self.status.in_flight.discard(message_id)

    def _blocked(self, exc: BlockedError) -> float:
        self.status.blocked_service = exc.service
        self.status.blocked_reason = exc.reason
        self.status.blocked_until = self._clock() + timedelta(seconds=BLOCKED_PAUSE_SECONDS)
        logger.error("Paused: %s. Next check in %ds", exc, BLOCKED_PAUSE_SECONDS)
        return BLOCKED_PAUSE_SECONDS

    def _next_delay(self) -> float:
        """Sleep until the next poll, or earlier if a retry becomes due before that."""
        next_due = self.pipeline.store.next_due_at()
        if next_due is None:
            return self._poll_seconds
        seconds_until_due = (next_due - self._clock()).total_seconds()
        return max(1.0, min(self._poll_seconds, seconds_until_due))


async def _wait_any(stop: asyncio.Event, wake: asyncio.Event, seconds: float) -> None:
    waiters = [asyncio.create_task(stop.wait()), asyncio.create_task(wake.wait())]
    try:
        await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
