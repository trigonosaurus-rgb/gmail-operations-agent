"""Server-sent events: the store's event log, pushed live and replayed after reconnects.

The log in SQLite is the source of truth, and every event has an increasing id.
A client that reconnects sends the last id it saw (`Last-Event-ID`) and first gets
what it missed from the log, then live events. A slow client never blocks the
worker: when its queue fills up, its stream closes and it catches up on reconnect.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi.sse import ServerSentEvent

from gmail_operations_agent.api.schemas import EventOut, MessageSummary
from gmail_operations_agent.store import Event, Store

QUEUE_SIZE = 256
REPLAY_LIMIT = 500
RETRY_MS = 3000


@dataclass(eq=False)
class Subscription:
    owner: str
    queue: asyncio.Queue[ServerSentEvent] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))
    overflowed: bool = False


class EventHub:
    def __init__(self, store: Store) -> None:
        self._store = store
        self._subscriptions: set[Subscription] = set()
        store.subscribe(self._publish)

    def close(self) -> None:
        self._store.unsubscribe(self._publish)

    @property
    def subscribers(self) -> int:
        return len(self._subscriptions)

    def message(self, event: Event) -> ServerSentEvent:
        """The wire form: the event plus the message's current summary, so lists update in place."""
        record = self._store.get_message(event.message_id) if event.message_id else None
        payload = {
            "event": EventOut.of(event).model_dump(mode="json"),
            "message": MessageSummary.of(record).model_dump(mode="json") if record else None,
        }
        return ServerSentEvent(id=str(event.id), event=event.type, data=payload)

    def _publish(self, event: Event) -> None:
        targets = [s for s in self._subscriptions if s.owner == event.owner and not s.overflowed]
        if not targets:
            return
        message = self.message(event)
        for subscription in targets:
            try:
                subscription.queue.put_nowait(message)
            except asyncio.QueueFull:
                subscription.overflowed = True

    async def stream(self, owner: str, after: int | None) -> AsyncIterator[ServerSentEvent]:
        subscription = Subscription(owner)
        self._subscriptions.add(subscription)  # before the replay, so nothing slips between
        try:
            last = self._store.last_event_id() if after is None else after
            yield ServerSentEvent(event="ready", data={"cursor": last}, retry=RETRY_MS)
            if after is not None:
                backlog = self._store.events_after(after, limit=REPLAY_LIMIT + 1, owner=owner)
                if len(backlog) > REPLAY_LIMIT or after > self._store.last_event_id():
                    # Too far behind, or a cursor from a database that was since replaced
                    # (a redeploy): tell the client to reload its lists instead.
                    last = self._store.last_event_id()
                    yield ServerSentEvent(id=str(last), event="reset", data={"cursor": last})
                else:
                    for event in backlog:
                        yield self.message(event)
                        last = event.id
            while True:
                if subscription.overflowed and subscription.queue.empty():
                    return  # the client reconnects with Last-Event-ID and replays the gap
                message = await subscription.queue.get()
                if message.id is not None and int(message.id) <= last:
                    continue  # already sent during the replay
                last = int(message.id) if message.id is not None else last
                yield message
        finally:
            self._subscriptions.discard(subscription)
