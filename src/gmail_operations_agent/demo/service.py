"""Visitor sandboxes, quotas, the test-email form and the opening scenario.

Every visitor gets a private copy of the seed inbox (an *owner* in the store),
identified by a random cookie token. Quotas count per client address, hashed with
a secret salt that changes daily, so no address is stored and hashes from different
days cannot be linked.
"""

import asyncio
import contextlib
import hashlib
import hmac
import logging
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from gmail_operations_agent.demo.data import SEED, DemoData, compose_email
from gmail_operations_agent.demo.llm import DemoLLM
from gmail_operations_agent.domain import ActionKind, Email
from gmail_operations_agent.pipeline import InvalidTransitionError, Pipeline
from gmail_operations_agent.store import Clock, Event, MessageRecord, Store, utcnow

logger = logging.getLogger(__name__)

SANDBOX_TOUCH_SECONDS = 60
CLEANUP_SECONDS = 600
SCENARIO_DELAY_SECONDS = 1.5
SIMULATED_NOTION_ERROR = (
    "Notion API 400 validation_error: Priority is expected to be select."
    " (Simulated by the demo; Retry succeeds.)"
)


class DemoLimitError(Exception):
    """A per-visitor limit was reached (HTTP 429)."""


class DemoSessionGoneError(Exception):
    """A change was sent for a sandbox that no longer exists (HTTP 410)."""


class DemoUnavailableError(Exception):
    """The live model cannot take this email right now (HTTP 503)."""


@dataclass(frozen=True)
class DemoLimits:
    daily_quota: int = 5
    monthly_budget_usd: float = 5.0
    sandbox_ttl_hours: float = 24
    max_sandboxes: int = 500
    sandboxes_per_visitor: int = 20
    max_body_chars: int = 8000


@dataclass(frozen=True)
class Quota:
    limit: int
    used: int
    resets_at: datetime

    @property
    def left(self) -> int:
        return max(self.limit - self.used, 0)


@dataclass(frozen=True)
class Session:
    owner: str
    visitor: str
    new_token: str | None  # set when a sandbox was just created; goes into the cookie


class DemoService:
    def __init__(
        self,
        store: Store,
        pipeline: Pipeline,
        llm: DemoLLM,
        data: DemoData,
        limits: DemoLimits,
        secret: bytes,
        wake: Callable[[], None],
        clock: Clock = utcnow,
        scenario_delay: float = SCENARIO_DELAY_SECONDS,
    ) -> None:
        self.store = store
        self.pipeline = pipeline
        self.llm = llm
        self.data = data
        self.limits = limits
        self._secret = secret
        self._wake = wake
        self._clock = clock
        self._scenario_delay = scenario_delay
        self._approve_later: set[str] = set()
        self._fail_once: set[str] = set()
        store.subscribe(self._on_event)

    # --- identity ----------------------------------------------------------------------

    def visitor_key(self, client_address: str) -> str:
        day = self._clock().date().isoformat()
        digest = hmac.new(self._secret, f"{day}|{client_address}".encode(), hashlib.sha256)
        return digest.hexdigest()[:24]

    @staticmethod
    def owner_for(token: str) -> str:
        # The owner is a hash of the cookie, so ids in logs and URLs never reveal the token.
        return "sb" + hashlib.sha256(token.encode()).hexdigest()[:14]

    def session(self, token: str | None, client_address: str, create: bool = True) -> Session:
        """The visitor's sandbox; a new one if they have none and `create` is set."""
        visitor = self.visitor_key(client_address)
        if token:
            owner = self.owner_for(token)
            seen = self.store.sandbox_last_seen(owner)
            if seen is not None:
                if (self._clock() - seen).total_seconds() > SANDBOX_TOUCH_SECONDS:
                    self.store.touch_sandbox(owner)
                return Session(owner, visitor, None)
        if not create:
            raise DemoSessionGoneError("Your demo session has expired. Reload the page.")
        return self._new_session(visitor)

    def reset(self, owner: str, client_address: str) -> Session:
        visitor = self.visitor_key(client_address)
        session = self._new_session(visitor)  # checks the limit before deleting anything
        self._delete([owner])
        return session

    def _new_session(self, visitor: str) -> Session:
        created = self.store.demo_usage_since(visitor, "sandbox", self._start_of_day())
        if created >= self.limits.sandboxes_per_visitor:
            raise DemoLimitError("Too many demo sessions from your network today.")
        token = secrets.token_urlsafe(18)
        owner = self.owner_for(token)
        self.create_sandbox(owner)
        self.store.record_demo_usage(visitor, "sandbox")
        return Session(owner, visitor, token)

    # --- sandboxes ---------------------------------------------------------------------

    def create_sandbox(self, owner: str) -> None:
        now = self._clock()
        self.store.add_sandbox(owner)
        for seed in sorted(SEED, key=lambda s: -s.minutes_ago):  # oldest first
            fields = self.data.seed_emails[seed.case]
            message_id = f"{owner}-{seed.case}"
            email = Email.model_validate(
                {
                    **fields,
                    "id": message_id,
                    "thread_id": message_id,
                    "source": "demo",
                    "message_id_header": f"<{message_id}@demo.local>",
                    "received_at": now - timedelta(minutes=seed.minutes_ago),
                }
            )
            self.pipeline.add_email(email, owner)
            if seed.scenario:
                self._approve_later.add(message_id)
            if seed.scenario == "approve_and_fail":
                self._fail_once.add(message_id)
        self._enforce_cap()
        self._wake()

    def cleanup(self) -> int:
        now = self._clock()
        stale = self.store.stale_sandboxes(
            self.limits.max_sandboxes, now - timedelta(hours=self.limits.sandbox_ttl_hours)
        )
        self._delete(stale)
        self.store.prune_demo_usage(now - timedelta(days=2))
        if stale:
            logger.info("Removed %d idle demo sandbox(es)", len(stale))
        return len(stale)

    def _enforce_cap(self) -> None:
        self._delete(self.store.stale_sandboxes(self.limits.max_sandboxes))

    def _delete(self, owners: list[str]) -> None:
        for owner in owners:
            self._forget(owner)
            self.store.delete_sandbox(owner)

    async def run_cleanup(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                self.cleanup()
            except Exception:
                logger.exception("Demo cleanup failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), CLEANUP_SECONDS)

    def _forget(self, owner: str) -> None:
        prefix = f"{owner}-"
        self._approve_later = {mid for mid in self._approve_later if not mid.startswith(prefix)}
        self._fail_once = {mid for mid in self._fail_once if not mid.startswith(prefix)}

    # --- the opening scenario ----------------------------------------------------------

    def _on_event(self, event: Event) -> None:
        if event.type == "awaiting_approval" and event.message_id in self._approve_later:
            self._approve_later.discard(event.message_id)
            loop = asyncio.get_running_loop()
            loop.call_later(self._scenario_delay, self._scenario_approve, event.message_id)

    def _scenario_approve(self, message_id: str) -> None:
        try:
            self.pipeline.approve(message_id, by="demo scenario")
        except (KeyError, InvalidTransitionError):
            return  # the visitor decided first, or the sandbox is gone
        self._wake()

    def sandbox_failure(self, kind: ActionKind, email: Email) -> str | None:
        """Failure hook for the sandboxed sinks: one scripted Notion error per scenario."""
        if kind == ActionKind.NOTION_TASK and email.id in self._fail_once:
            self._fail_once.discard(email.id)
            return SIMULATED_NOTION_ERROR
        return None

    # --- the test-email form -----------------------------------------------------------

    def quota(self, visitor: str) -> Quota:
        start = self._start_of_day()
        used = self.store.demo_usage_since(visitor, "email", start)
        return Quota(self.limits.daily_quota, used, start + timedelta(days=1))

    def has_budget(self) -> bool:
        cap = self.limits.monthly_budget_usd
        start = self._clock().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return self.store.llm_spend_since(start, provider="openai") < cap

    def submit(
        self, session: Session, sender_name: str, sender_address: str, subject: str, body: str
    ) -> tuple[MessageRecord, bool]:
        """Add a visitor's test email to their inbox. Returns it and whether it is a replay."""
        if self.quota(session.visitor).left <= 0:
            raise DemoLimitError("You have used today's test emails. Come back tomorrow.")
        email = compose_email(
            id=f"{session.owner}-t{uuid.uuid4().hex[:10]}",
            sender_name=sender_name,
            sender_address=sender_address,
            subject=subject,
            body=body,
            received_at=self._clock(),
            max_body_chars=self.limits.max_body_chars,
        )
        recorded = self.llm.can_replay(email)
        if not recorded and not self.llm.live_available():
            raise DemoUnavailableError(
                "The live model is off right now."
                " The presets still work: they replay recorded runs."
            )
        self.pipeline.add_email(email, session.owner)
        self.store.record_demo_usage(session.visitor, "email")
        self._wake()
        record = self.store.get_message(email.id)
        assert record is not None
        return record, recorded

    def _start_of_day(self) -> datetime:
        return self._clock().replace(hour=0, minute=0, second=0, microsecond=0)
