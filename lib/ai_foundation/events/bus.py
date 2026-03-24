"""
Event Bus — in-process pub/sub for agent-to-agent communication.

Uses asyncio for event dispatch. Can be backed by Redis Streams for
cross-process communication in production (future enhancement).

Agents publish events when noteworthy things happen; other agents
subscribe to event types they care about.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from .schemas import HealthEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[HealthEvent], Awaitable[None]]


class EventBus:
    """In-process async event bus for health events.

    Example::

        bus = EventBus()

        # Subscribe
        async def on_meal(event: HealthEvent):
            print(f"Meal logged: {event.data}")

        bus.subscribe(["meal_logged"], on_meal)

        # Publish
        await bus.publish(HealthEvent(
            event_type="meal_logged",
            patient_id="p123",
            data={"calories": 450, "meal_type": "lunch"},
            source_agent="meal_agent",
        ))
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []
        self._event_count: int = 0

    def subscribe(
        self,
        event_types: list[str],
        handler: EventHandler,
    ) -> None:
        """Subscribe a handler to specific event types.

        Args:
            event_types: List of event type strings to listen for.
            handler: Async callable that receives a ``HealthEvent``.
        """
        for event_type in event_types:
            self._handlers[event_type].append(handler)
            logger.debug(
                "Subscribed handler %s to %r",
                handler.__qualname__,
                event_type,
            )

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe a handler to ALL event types (e.g. for logging/tracing)."""
        self._global_handlers.append(handler)

    async def publish(self, event: HealthEvent) -> None:
        """Publish an event to all matching subscribers.

        Handlers are invoked concurrently. Errors in individual handlers
        are logged but do not prevent other handlers from running.
        """
        self._event_count += 1

        handlers: list[EventHandler] = [
            *self._handlers.get(event.event_type, []),
            *self._global_handlers,
        ]

        if not handlers:
            logger.debug("No handlers for event %s", event.event_type)
            return

        logger.debug(
            "Publishing %s to %d handlers (patient=%s)",
            event.event_type,
            len(handlers),
            event.patient_id,
        )

        tasks = [
            asyncio.create_task(self._safe_invoke(handler, event))
            for handler in handlers
        ]
        await asyncio.gather(*tasks)

    async def _safe_invoke(
        self, handler: EventHandler, event: HealthEvent
    ) -> None:
        """Invoke a handler, catching and logging any errors."""
        try:
            await handler(event)
        except Exception as exc:
            logger.error(
                "Event handler %s failed for %s: %s",
                handler.__qualname__,
                event.event_type,
                exc,
            )

    def unsubscribe(
        self,
        event_types: list[str],
        handler: EventHandler,
    ) -> None:
        """Remove a handler from specific event types."""
        for event_type in event_types:
            handlers = self._handlers.get(event_type, [])
            if handler in handlers:
                handlers.remove(handler)

    @property
    def event_count(self) -> int:
        """Total number of events published since creation."""
        return self._event_count

    def list_subscriptions(self) -> dict[str, int]:
        """Return event types and their handler counts."""
        return {
            event_type: len(handlers)
            for event_type, handlers in self._handlers.items()
            if handlers
        }
