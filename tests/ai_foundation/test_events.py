"""Tests for EventBus — async pub/sub for agent-to-agent communication."""

import pytest

from lib.ai_foundation.events.bus import EventBus
from lib.ai_foundation.events.schemas import HealthEvent, HealthEventType


class TestHealthEvent:
    def test_event_id_generated(self):
        e = HealthEvent(event_type="test", patient_id="p1")
        assert e.event_id.startswith("evt_")

    def test_event_type_enum(self):
        e = HealthEvent(event_type=HealthEventType.MEAL_LOGGED, patient_id="p1", data={"cal": 500})
        assert e.event_type == "meal_logged"
        assert e.data["cal"] == 500


class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, event_bus):
        received = []

        async def handler(event: HealthEvent):
            received.append(event)

        event_bus.subscribe(["meal_logged"], handler)
        await event_bus.publish(HealthEvent(
            event_type="meal_logged", patient_id="p1", data={"cal": 500},
        ))
        assert len(received) == 1
        assert received[0].data["cal"] == 500

    @pytest.mark.asyncio
    async def test_no_cross_delivery(self, event_bus):
        received = []

        async def handler(event: HealthEvent):
            received.append(event)

        event_bus.subscribe(["meal_logged"], handler)
        await event_bus.publish(HealthEvent(
            event_type="glucose_spike", patient_id="p1",
        ))
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_multiple_handlers(self, event_bus):
        results = {"a": 0, "b": 0}

        async def handler_a(event): results["a"] += 1
        async def handler_b(event): results["b"] += 1

        event_bus.subscribe(["test"], handler_a)
        event_bus.subscribe(["test"], handler_b)
        await event_bus.publish(HealthEvent(event_type="test", patient_id="p1"))
        assert results == {"a": 1, "b": 1}

    @pytest.mark.asyncio
    async def test_subscribe_all(self, event_bus):
        received = []

        async def global_handler(event): received.append(event.event_type)

        event_bus.subscribe_all(global_handler)
        await event_bus.publish(HealthEvent(event_type="a", patient_id="p1"))
        await event_bus.publish(HealthEvent(event_type="b", patient_id="p1"))
        assert received == ["a", "b"]

    @pytest.mark.asyncio
    async def test_handler_error_doesnt_block_others(self, event_bus):
        results = []

        async def bad_handler(event): raise ValueError("boom")
        async def good_handler(event): results.append("ok")

        event_bus.subscribe(["test"], bad_handler)
        event_bus.subscribe(["test"], good_handler)
        await event_bus.publish(HealthEvent(event_type="test", patient_id="p1"))
        assert results == ["ok"]

    @pytest.mark.asyncio
    async def test_unsubscribe(self, event_bus):
        received = []
        async def handler(event): received.append(1)

        event_bus.subscribe(["test"], handler)
        await event_bus.publish(HealthEvent(event_type="test", patient_id="p1"))
        assert len(received) == 1

        event_bus.unsubscribe(["test"], handler)
        await event_bus.publish(HealthEvent(event_type="test", patient_id="p1"))
        assert len(received) == 1  # no new delivery

    @pytest.mark.asyncio
    async def test_event_count(self, event_bus):
        assert event_bus.event_count == 0
        await event_bus.publish(HealthEvent(event_type="a", patient_id="p1"))
        await event_bus.publish(HealthEvent(event_type="b", patient_id="p2"))
        assert event_bus.event_count == 2

    def test_list_subscriptions(self, event_bus):
        async def h(e): pass
        event_bus.subscribe(["a", "b"], h)
        subs = event_bus.list_subscriptions()
        assert subs == {"a": 1, "b": 1}
