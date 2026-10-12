"""The processing state machine for one message.

    NEW ──triage──▶ AWAITING_APPROVAL ──approve/reject──▶ ACTING ──▶ DONE | REJECTED
     │                                                     ▲
     └──────────────(auto mode, or nothing to approve)─────┘
    Transient errors keep the state and schedule a retry; permanent errors and
    exhausted attempts move the message to DEAD, from where a person can retry it.

Every step is persisted before and after its side effect, so the process can be
killed at any point and resume without losing or duplicating work.
"""

import logging
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from gmail_operations_agent.domain import (
    NEEDS_APPROVAL,
    ActionKind,
    ActionStatus,
    Decision,
    Email,
    MessageState,
    Overrides,
    Triage,
)
from gmail_operations_agent.errors import AgentError, BlockedError, PermanentError, TransientError
from gmail_operations_agent.integrations.base import ActionSink, MailSource
from gmail_operations_agent.llm.base import LLMProvider
from gmail_operations_agent.mime import parse_email
from gmail_operations_agent.rules import apply_guardrails, plan_actions
from gmail_operations_agent.store import ActionRecord, Clock, MessageRecord, Store, utcnow

logger = logging.getLogger(__name__)


class InvalidTransitionError(Exception):
    """A person asked for something the message's current state does not allow."""


@dataclass(frozen=True)
class PipelineConfig:
    mode: Literal["review", "auto"] = "review"
    max_attempts: int = 8
    retry_base_seconds: float = 60
    retry_max_seconds: float = 3600
    max_body_chars: int = 8000
    daily_budget_usd: float | None = 1.0


class Pipeline:
    def __init__(
        self,
        store: Store,
        llm: LLMProvider,
        sinks: Sequence[ActionSink],
        config: PipelineConfig,
        clock: Clock = utcnow,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.store = store
        self.llm = llm
        self.config = config
        self._sinks = {sink.kind: sink for sink in sinks}
        self._clock = clock
        self._jitter = jitter

    @property
    def enabled_actions(self) -> set[ActionKind]:
        return set(self._sinks)

    def sink(self, kind: ActionKind) -> ActionSink | None:
        return self._sinks.get(kind)

    # --- ingestion ---------------------------------------------------------------------

    async def ingest(self, source: MailSource) -> int:
        added = 0
        for raw in await source.poll(self.store.has_message):
            try:
                email = parse_email(
                    raw.raw,
                    id=raw.id,
                    thread_id=raw.thread_id,
                    source=source.name,
                    max_body_chars=self.config.max_body_chars,
                    web_url=raw.web_url,
                )
            except Exception as exc:  # the parser is lenient; this is the last line of defence
                logger.exception("Could not parse message %s", raw.id)
                placeholder = Email(
                    id=raw.id,
                    thread_id=raw.thread_id,
                    source=source.name,
                    sender_address="unknown",
                    subject="(unparseable message)",
                    web_url=raw.web_url,
                )
                if self.store.add_message(placeholder, MessageState.DEAD, f"parse error: {exc}"):
                    self.store.add_event(raw.id, "dead", {"error": f"parse error: {exc}"})
                continue
            if self.add_email(email):
                added += 1
        return added

    def add_email(self, email: Email) -> bool:
        if not self.store.add_message(email):
            return False
        self.store.add_event(
            email.id, "ingested", {"subject": email.subject, "from": email.sender_display}
        )
        logger.info("Ingested message %s", email.id)
        return True

    # --- processing --------------------------------------------------------------------

    async def process(self, message_id: str) -> None:
        record = self.store.get_message(message_id)
        if record is None:
            return
        try:
            if record.state == MessageState.NEW:
                record = await self._triage(record)
            if record.state == MessageState.ACTING:
                await self._act(record)
        except BlockedError:
            raise  # the worker pauses; the message keeps its attempts
        except TransientError as exc:
            self._retry_later(record, str(exc))
        except PermanentError as exc:
            self._dead(record, str(exc))
        except Exception as exc:
            logger.exception("Unexpected error while processing %s", message_id)
            self._retry_later(record, f"unexpected error: {exc!r}")

    async def _triage(self, record: MessageRecord) -> MessageRecord:
        self._check_budget()
        email = record.email
        try:
            outcome = await self.llm.triage(email)
        except AgentError as exc:
            self.store.add_llm_call(
                email.id, None, error=str(exc), provider=self.llm.name, model=self.llm.model
            )
            raise
        self.store.add_llm_call(email.id, outcome.usage)

        triage, notes = apply_guardrails(email, outcome.triage)
        actions = plan_actions(triage, self.enabled_actions)
        needs_review = self.config.mode == "review" and any(a in NEEDS_APPROVAL for a in actions)
        state = MessageState.AWAITING_APPROVAL if needs_review else MessageState.ACTING
        decision = None if needs_review else Decision.AUTO
        self.store.save_triage(email.id, triage, notes, actions, state, decision)
        self.store.add_event(
            email.id,
            "triaged",
            {
                "category": triage.category,
                "priority": triage.priority,
                "risk": triage.risk,
                "actions": actions,
                "notes": notes,
                "model": outcome.usage.model,
                "cost_usd": outcome.usage.cost_usd,
                "latency_ms": outcome.usage.latency_ms,
            },
        )
        logger.info(
            "Triaged %s: %s/%s, risk %s, actions %s",
            email.id,
            triage.category.value,
            triage.priority.value,
            triage.risk.value,
            ",".join(actions),
        )
        if needs_review:
            self.store.add_event(email.id, "awaiting_approval")
        updated = self.store.get_message(email.id)
        assert updated is not None
        return updated

    async def _act(self, record: MessageRecord) -> None:
        email, triage = record.email, record.effective_triage
        if triage is None:
            raise PermanentError("no triage to act on")
        actions = self.store.get_actions(email.id)
        transient: list[str] = []
        permanent: list[str] = []

        # Independent actions: one failing does not stop the others.
        for action in actions:
            if action.kind == ActionKind.MARK_PROCESSED:
                continue
            if action.status == ActionStatus.FAILED:
                permanent.append(f"{action.kind}: {action.last_error}")
                continue
            if action.status in (ActionStatus.DONE, ActionStatus.SKIPPED):
                continue
            try:
                await self._run_action(email, triage, action)
            except BlockedError:
                raise
            except PermanentError as exc:
                permanent.append(f"{action.kind}: {exc}")
            except TransientError as exc:
                transient.append(f"{action.kind}: {exc}")

        if permanent:
            self._dead(record, "; ".join(permanent))
            return
        if transient:
            raise TransientError("; ".join(transient))

        # Only after everything else succeeded: label the email as processed in the source.
        final = next((a for a in actions if a.kind == ActionKind.MARK_PROCESSED), None)
        if final and final.status not in (ActionStatus.DONE, ActionStatus.SKIPPED):
            await self._run_action(email, triage, final)

        state = MessageState.REJECTED if record.decision == Decision.REJECTED else MessageState.DONE
        self.store.set_state(email.id, state)
        self.store.add_event(email.id, state.value)
        logger.info("Message %s is %s", email.id, state.value)

    async def _run_action(self, email: Email, triage: Triage, action: ActionRecord) -> None:
        sink = self._sinks.get(action.kind)
        if sink is None:
            raise PermanentError(f"{action.kind} is no longer configured")

        result = None
        if action.status == ActionStatus.RUNNING or action.attempts > 0:
            # An earlier attempt may have reached the service: look before creating again.
            result = await sink.find_existing(email)
            if result:
                self.store.add_event(email.id, "action_recovered", {"kind": action.kind})

        if result is None:
            self.store.action_running(email.id, action.kind)
            self.store.add_event(email.id, "action_started", {"kind": action.kind})
            try:
                result = await sink.execute(email, triage)
            except PermanentError as exc:
                self.store.action_failed(email.id, action.kind, str(exc), permanent=True)
                self.store.add_event(
                    email.id, "action_failed", {"kind": action.kind, "error": str(exc)}
                )
                raise
            except AgentError as exc:
                self.store.action_failed(email.id, action.kind, str(exc), permanent=False)
                self.store.add_event(
                    email.id, "action_failed", {"kind": action.kind, "error": str(exc)}
                )
                raise
            except Exception as exc:
                logger.exception("Unexpected error in %s for %s", action.kind, email.id)
                self.store.action_failed(email.id, action.kind, repr(exc), permanent=False)
                raise TransientError(f"unexpected error: {exc!r}") from exc

        self.store.action_done(email.id, action.kind, result)
        self.store.add_event(
            email.id,
            "action_done",
            {"kind": action.kind, "url": result.url, "external_id": result.external_id},
        )

    # --- failure handling --------------------------------------------------------------

    def _retry_later(self, record: MessageRecord, error: str) -> None:
        attempts = record.attempts + 1
        if attempts >= self.config.max_attempts:
            self._dead(record, f"gave up after {attempts} attempts: {error}", attempts)
            return
        # Exponential backoff with ±20% jitter, so a burst of failures does not retry in lockstep.
        delay = min(
            self.config.retry_base_seconds * 2 ** (attempts - 1), self.config.retry_max_seconds
        )
        delay *= 0.8 + 0.4 * self._jitter()
        next_at = self._clock() + timedelta(seconds=delay)
        self.store.schedule_retry(record.id, attempts, next_at, error)
        self.store.add_event(
            record.id,
            "retry_scheduled",
            {"attempt": attempts, "next_attempt_at": next_at.isoformat(), "error": error},
        )
        logger.warning(
            "Message %s failed (attempt %d/%d), retrying in %ds: %s",
            record.id,
            attempts,
            self.config.max_attempts,
            delay,
            error,
        )

    def _dead(self, record: MessageRecord, error: str, attempts: int | None = None) -> None:
        self.store.mark_dead(record.id, error, attempts)
        self.store.add_event(record.id, "dead", {"error": error})
        logger.error("Message %s moved to dead letters: %s", record.id, error)

    def _check_budget(self) -> None:
        cap = self.config.daily_budget_usd
        if not cap:
            return
        start_of_day = self._clock().replace(hour=0, minute=0, second=0, microsecond=0)
        spent = self.store.llm_spend_since(start_of_day)
        if spent >= cap:
            raise BlockedError("budget", f"daily LLM budget of ${cap:.2f} reached (${spent:.4f})")

    # --- human decisions ---------------------------------------------------------------

    def approve(self, message_id: str, overrides: Overrides | None = None) -> None:
        self._require(message_id, MessageState.AWAITING_APPROVAL)
        if overrides:
            self.store.set_overrides(message_id, overrides)
            skip = [kind for kind in overrides.skip if kind != ActionKind.MARK_PROCESSED]
            self.store.skip_actions(message_id, skip)
        self.store.set_state(message_id, MessageState.ACTING, Decision.APPROVED)
        self.store.add_event(message_id, "approved")

    def reject(self, message_id: str) -> None:
        self._require(message_id, MessageState.AWAITING_APPROVAL)
        skip = [kind for kind in self.enabled_actions if kind != ActionKind.MARK_PROCESSED]
        self.store.skip_actions(message_id, skip)
        self.store.set_state(message_id, MessageState.ACTING, Decision.REJECTED)
        self.store.add_event(message_id, "rejected")

    def retry(self, message_id: str) -> None:
        record = self._require(message_id, MessageState.DEAD)
        if record.triage is None:
            state = MessageState.NEW
        elif record.decision is None:
            state = MessageState.AWAITING_APPROVAL
        else:
            state = MessageState.ACTING
        self.store.reset_for_retry(message_id, state)
        self.store.add_event(message_id, "retry_requested", {"state": state})

    def _require(self, message_id: str, state: MessageState) -> MessageRecord:
        record = self.store.get_message(message_id)
        if record is None:
            raise KeyError(message_id)
        if record.state != state:
            raise InvalidTransitionError(f"message is {record.state.value}, expected {state.value}")
        return record
