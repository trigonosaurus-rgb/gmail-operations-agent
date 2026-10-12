"""SQLite store: the single source of truth for message state, actions, LLM calls and events.

All access happens on the event-loop thread through one connection. Each call is a
short local transaction, so blocking is negligible and there are no locking surprises.
"""

import json
import sqlite3
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from gmail_operations_agent.domain import (
    ACTION_ORDER,
    ActionKind,
    ActionResult,
    ActionStatus,
    Decision,
    Email,
    MessageState,
    Overrides,
    Triage,
    Usage,
)

Clock = Callable[[], datetime]


def utcnow() -> datetime:
    return datetime.now(UTC)


def _ts(value: datetime) -> str:
    # Fixed width, so ISO strings compare correctly as text in SQL.
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


MIGRATIONS = [
    """
    CREATE TABLE messages (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        state TEXT NOT NULL,
        email_json TEXT NOT NULL,
        triage_json TEXT,
        overrides_json TEXT,
        notes_json TEXT,
        decision TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX messages_due ON messages (state, next_attempt_at);
    CREATE INDEX messages_created ON messages (created_at);

    CREATE TABLE actions (
        message_id TEXT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        external_id TEXT,
        url TEXT,
        preview_json TEXT,
        last_error TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (message_id, kind)
    );

    CREATE TABLE llm_calls (
        id INTEGER PRIMARY KEY,
        message_id TEXT,
        provider TEXT,
        model TEXT,
        prompt_version TEXT,
        input_tokens INTEGER,
        cached_tokens INTEGER,
        output_tokens INTEGER,
        cost_usd REAL,
        latency_ms INTEGER,
        ok INTEGER NOT NULL,
        error TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX llm_calls_created ON llm_calls (created_at);

    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT,
        type TEXT NOT NULL,
        data_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """,
]


class ActionRecord(BaseModel):
    kind: ActionKind
    status: ActionStatus
    attempts: int
    external_id: str | None
    url: str | None
    preview: dict[str, Any]
    last_error: str | None
    updated_at: datetime


class MessageRecord(BaseModel):
    id: str
    source: str
    state: MessageState
    email: Email
    triage: Triage | None
    overrides: Overrides
    notes: list[str]
    decision: Decision | None
    attempts: int
    next_attempt_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def effective_triage(self) -> Triage | None:
        return self.overrides.apply(self.triage) if self.triage else None


class Event(BaseModel):
    id: int
    message_id: str | None
    type: str
    data: dict[str, Any]
    created_at: datetime


class Store:
    def __init__(self, path: Path | str, clock: Clock = utcnow) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._clock = clock
        self._listeners: list[Callable[[Event], None]] = []
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with self.transaction():
                for statement in script.split(";"):
                    if statement.strip():
                        self._db.execute(statement)
                self._db.execute(f"PRAGMA user_version = {number}")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")

    def _now(self) -> str:
        return _ts(self._clock())

    # --- messages ----------------------------------------------------------------------

    def has_message(self, message_id: str) -> bool:
        row = self._db.execute("SELECT 1 FROM messages WHERE id = ?", (message_id,)).fetchone()
        return row is not None

    def add_message(
        self, email: Email, state: MessageState = MessageState.NEW, error: str | None = None
    ) -> bool:
        """Insert a new message; returns False if it is already known."""
        now = self._now()
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO messages (id, source, state, email_json, last_error,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (email.id, email.source, state, email.model_dump_json(), error, now, now),
        )
        return cursor.rowcount == 1

    def get_message(self, message_id: str) -> MessageRecord | None:
        row = self._db.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return self._message(row) if row else None

    def list_messages(
        self,
        states: list[MessageState] | None = None,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[MessageRecord]:
        sql = "SELECT * FROM messages WHERE 1 = 1"
        params: list[Any] = []
        if states:
            sql += f" AND state IN ({', '.join('?' for _ in states)})"
            params += list(states)
        if before:
            sql += " AND created_at < ?"
            params.append(_ts(before))
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._message(row) for row in self._db.execute(sql, params)]

    def due_message_ids(self, limit: int = 50) -> list[str]:
        rows = self._db.execute(
            "SELECT id FROM messages WHERE state IN (?, ?)"
            " AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
            " ORDER BY created_at LIMIT ?",
            (MessageState.NEW, MessageState.ACTING, self._now(), limit),
        )
        return [row["id"] for row in rows]

    def next_due_at(self) -> datetime | None:
        row = self._db.execute(
            "SELECT MIN(next_attempt_at) FROM messages WHERE state IN (?, ?)",
            (MessageState.NEW, MessageState.ACTING),
        ).fetchone()
        return _dt(row[0])

    def save_triage(
        self,
        message_id: str,
        triage: Triage,
        notes: list[str],
        actions: list[ActionKind],
        state: MessageState,
        decision: Decision | None,
    ) -> None:
        now = self._now()
        with self.transaction():
            self._db.execute(
                "UPDATE messages SET triage_json = ?, notes_json = ?, state = ?, decision = ?,"
                " attempts = 0, next_attempt_at = NULL, last_error = NULL, updated_at = ?"
                " WHERE id = ?",
                (triage.model_dump_json(), json.dumps(notes), state, decision, now, message_id),
            )
            self._db.executemany(
                "INSERT OR IGNORE INTO actions (message_id, kind, status, updated_at)"
                " VALUES (?, ?, ?, ?)",
                [(message_id, kind, ActionStatus.PENDING, now) for kind in actions],
            )

    def set_state(
        self, message_id: str, state: MessageState, decision: Decision | None = None
    ) -> None:
        self._db.execute(
            "UPDATE messages SET state = ?, decision = COALESCE(?, decision),"
            " next_attempt_at = NULL, last_error = NULL, updated_at = ? WHERE id = ?",
            (state, decision, self._now(), message_id),
        )

    def schedule_retry(
        self, message_id: str, attempts: int, next_attempt_at: datetime, error: str
    ) -> None:
        self._db.execute(
            "UPDATE messages SET attempts = ?, next_attempt_at = ?, last_error = ?,"
            " updated_at = ? WHERE id = ?",
            (attempts, _ts(next_attempt_at), error, self._now(), message_id),
        )

    def mark_dead(self, message_id: str, error: str, attempts: int | None = None) -> None:
        self._db.execute(
            "UPDATE messages SET state = ?, last_error = ?, next_attempt_at = NULL,"
            " attempts = COALESCE(?, attempts), updated_at = ? WHERE id = ?",
            (MessageState.DEAD, error, attempts, self._now(), message_id),
        )

    def reset_for_retry(self, message_id: str, state: MessageState) -> None:
        now = self._now()
        with self.transaction():
            self._db.execute(
                "UPDATE messages SET state = ?, attempts = 0, next_attempt_at = NULL,"
                " last_error = NULL, updated_at = ? WHERE id = ?",
                (state, now, message_id),
            )
            self._db.execute(
                "UPDATE actions SET status = ?, last_error = NULL, updated_at = ?"
                " WHERE message_id = ? AND status = ?",
                (ActionStatus.PENDING, now, message_id, ActionStatus.FAILED),
            )

    def set_overrides(self, message_id: str, overrides: Overrides) -> None:
        self._db.execute(
            "UPDATE messages SET overrides_json = ?, updated_at = ? WHERE id = ?",
            (overrides.model_dump_json(), self._now(), message_id),
        )

    def _message(self, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=row["id"],
            source=row["source"],
            state=MessageState(row["state"]),
            email=Email.model_validate_json(row["email_json"]),
            triage=Triage.model_validate_json(row["triage_json"]) if row["triage_json"] else None,
            overrides=(
                Overrides.model_validate_json(row["overrides_json"])
                if row["overrides_json"]
                else Overrides()
            ),
            notes=json.loads(row["notes_json"]) if row["notes_json"] else [],
            decision=Decision(row["decision"]) if row["decision"] else None,
            attempts=row["attempts"],
            next_attempt_at=_dt(row["next_attempt_at"]),
            last_error=row["last_error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    # --- actions -----------------------------------------------------------------------

    def get_actions(self, message_id: str) -> list[ActionRecord]:
        rows = self._db.execute("SELECT * FROM actions WHERE message_id = ?", (message_id,))
        records = [
            ActionRecord(
                kind=ActionKind(row["kind"]),
                status=ActionStatus(row["status"]),
                attempts=row["attempts"],
                external_id=row["external_id"],
                url=row["url"],
                preview=json.loads(row["preview_json"]) if row["preview_json"] else {},
                last_error=row["last_error"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]
        return sorted(records, key=lambda record: ACTION_ORDER.index(record.kind))

    def action_running(self, message_id: str, kind: ActionKind) -> None:
        """Persist the intent before calling the external API (a write-ahead marker)."""
        self._db.execute(
            "UPDATE actions SET status = ?, attempts = attempts + 1, updated_at = ?"
            " WHERE message_id = ? AND kind = ?",
            (ActionStatus.RUNNING, self._now(), message_id, kind),
        )

    def action_done(self, message_id: str, kind: ActionKind, result: ActionResult) -> None:
        self._db.execute(
            "UPDATE actions SET status = ?, external_id = ?, url = ?, preview_json = ?,"
            " last_error = NULL, updated_at = ? WHERE message_id = ? AND kind = ?",
            (
                ActionStatus.DONE,
                result.external_id,
                result.url,
                json.dumps(result.preview, ensure_ascii=False, default=str),
                self._now(),
                message_id,
                kind,
            ),
        )

    def action_failed(self, message_id: str, kind: ActionKind, error: str, permanent: bool) -> None:
        # A transient failure goes back to PENDING; the attempt counter remembers that
        # the call was made, so the next try checks for an existing result first.
        status = ActionStatus.FAILED if permanent else ActionStatus.PENDING
        self._db.execute(
            "UPDATE actions SET status = ?, last_error = ?, updated_at = ?"
            " WHERE message_id = ? AND kind = ?",
            (status, error, self._now(), message_id, kind),
        )

    def skip_actions(self, message_id: str, kinds: Iterable[ActionKind]) -> None:
        self._db.executemany(
            "UPDATE actions SET status = ?, updated_at = ?"
            " WHERE message_id = ? AND kind = ? AND status = ?",
            [
                (ActionStatus.SKIPPED, self._now(), message_id, kind, ActionStatus.PENDING)
                for kind in kinds
            ],
        )

    # --- LLM calls ---------------------------------------------------------------------

    def add_llm_call(
        self,
        message_id: str | None,
        usage: Usage | None,
        error: str | None = None,
        provider: str = "",
        model: str = "",
    ) -> None:
        self._db.execute(
            "INSERT INTO llm_calls (message_id, provider, model, prompt_version, input_tokens,"
            " cached_tokens, output_tokens, cost_usd, latency_ms, ok, error, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message_id,
                usage.provider if usage else provider,
                usage.model if usage else model,
                usage.prompt_version if usage else None,
                usage.input_tokens if usage else None,
                usage.cached_tokens if usage else None,
                usage.output_tokens if usage else None,
                usage.cost_usd if usage else None,
                usage.latency_ms if usage else None,
                int(error is None),
                error,
                self._now(),
            ),
        )

    def llm_spend_since(self, since: datetime) -> float:
        row = self._db.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE created_at >= ?",
            (_ts(since),),
        ).fetchone()
        return float(row[0])

    # --- events ------------------------------------------------------------------------

    def subscribe(self, listener: Callable[[Event], None]) -> None:
        self._listeners.append(listener)

    def add_event(
        self, message_id: str | None, type: str, data: dict[str, Any] | None = None
    ) -> Event:
        now = self._now()
        payload = data or {}
        cursor = self._db.execute(
            "INSERT INTO events (message_id, type, data_json, created_at) VALUES (?, ?, ?, ?)",
            (message_id, type, json.dumps(payload, ensure_ascii=False, default=str), now),
        )
        assert cursor.lastrowid is not None
        event = Event(
            id=cursor.lastrowid,
            message_id=message_id,
            type=type,
            data=payload,
            created_at=datetime.fromisoformat(now),
        )
        for listener in self._listeners:
            listener(event)
        return event

    def events_after(
        self, after_id: int = 0, limit: int = 500, message_id: str | None = None
    ) -> list[Event]:
        sql = "SELECT * FROM events WHERE id > ?"
        params: list[Any] = [after_id]
        if message_id:
            sql += " AND message_id = ?"
            params.append(message_id)
        sql += " ORDER BY id LIMIT ?"
        params.append(limit)
        return [
            Event(
                id=row["id"],
                message_id=row["message_id"],
                type=row["type"],
                data=json.loads(row["data_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in self._db.execute(sql, params)
        ]

    # --- stats -------------------------------------------------------------------------

    def stats(self, since: datetime) -> dict[str, Any]:
        by_state = {
            row["state"]: row["n"]
            for row in self._db.execute("SELECT state, COUNT(*) AS n FROM messages GROUP BY state")
        }
        by_category = {
            row["category"]: row["n"]
            for row in self._db.execute(
                "SELECT json_extract(triage_json, '$.category') AS category, COUNT(*) AS n"
                " FROM messages WHERE triage_json IS NOT NULL GROUP BY category"
            )
        }
        llm = self._db.execute(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd), 0) AS cost,"
            " AVG(latency_ms) AS avg_latency, SUM(1 - ok) AS failures"
            " FROM llm_calls WHERE created_at >= ?",
            (_ts(since),),
        ).fetchone()
        return {
            "by_state": by_state,
            "by_category": by_category,
            "llm_calls": llm["calls"],
            "llm_failures": llm["failures"] or 0,
            "llm_cost_usd": round(llm["cost"], 6),
            "llm_avg_latency_ms": round(llm["avg_latency"]) if llm["avg_latency"] else None,
        }
