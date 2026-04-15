from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module, make_module


class TestFeedService:
    @pytest.mark.asyncio
    async def test_send_cheer_rejects_self_cheer(self, monkeypatch):
        async def fake_notify(*_args, **_kwargs):
            return None

        module = load_module(
            monkeypatch,
            "lib/services/gamification/feed_service.py",
            "gamification_test_feed_service_self_cheer",
            {
                "lib.services.gamification.notifications": make_module(
                    "lib.services.gamification.notifications",
                    send_gamification_notification=fake_notify,
                ),
            },
        )
        sender_id = uuid4()
        # send_cheer first loads the ActivityFeedEvent — provide one whose
        # actor_id matches sender_id so the self-cheer guard fires.
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(feed_id=uuid4(), actor_id=sender_id)]),
            ]
        )
        service = module.FeedService(postgres_store=None, xp_service=SimpleNamespace())

        with pytest.raises(ValueError, match="Cannot cheer your own event"):
            await service.send_cheer(
                sender_id=sender_id,
                feed_event_id=uuid4(),
                reaction="fire",
                postgres_session=session,
            )

    @pytest.mark.asyncio
    async def test_send_cheer_with_same_reaction_undoes(self, monkeypatch):
        """Tapping the same emoji twice undoes the cheer (replaces the old
        'reject duplicate' behavior)."""
        async def fake_notify(*_args, **_kwargs):
            return None

        module = load_module(
            monkeypatch,
            "lib/services/gamification/feed_service.py",
            "gamification_test_feed_service_undo",
            {
                "lib.services.gamification.notifications": make_module(
                    "lib.services.gamification.notifications",
                    send_gamification_notification=fake_notify,
                ),
            },
        )
        sender_id = uuid4()
        recipient_id = uuid4()
        existing_cheer = SimpleNamespace(
            cheer_id=uuid4(), sender_id=sender_id,
            feed_event_id=uuid4(), reaction="star",
        )
        session = FakeSession(
            results=[
                # Event lookup
                FakeScalarResult(values=[SimpleNamespace(feed_id=uuid4(), actor_id=recipient_id)]),
                # Buddy check (yes)
                FakeScalarResult(scalar=uuid4()),
                # Existing cheer with same reaction
                FakeScalarResult(values=[existing_cheer]),
            ]
        )
        # delete() is awaited on the session
        async def _async_delete(obj):
            return None
        session.delete = _async_delete
        service = module.FeedService(postgres_store=None, xp_service=SimpleNamespace())

        result = await service.send_cheer(
            sender_id=sender_id,
            feed_event_id=existing_cheer.feed_event_id,
            reaction="star",  # same as existing
            postgres_session=session,
        )
        # Same-reaction tap returns None (undone)
        assert result is None

    @pytest.mark.asyncio
    async def test_send_cheer_with_different_reaction_replaces(self, monkeypatch):
        """Different emoji on existing cheer replaces the reaction."""
        async def fake_notify(*_args, **_kwargs):
            return None

        module = load_module(
            monkeypatch,
            "lib/services/gamification/feed_service.py",
            "gamification_test_feed_service_replace",
            {
                "lib.services.gamification.notifications": make_module(
                    "lib.services.gamification.notifications",
                    send_gamification_notification=fake_notify,
                ),
            },
        )
        sender_id = uuid4()
        recipient_id = uuid4()
        existing_cheer = SimpleNamespace(
            cheer_id=uuid4(), sender_id=sender_id,
            feed_event_id=uuid4(), reaction="fire",
        )
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(feed_id=uuid4(), actor_id=recipient_id)]),
                FakeScalarResult(scalar=uuid4()),  # buddy check
                FakeScalarResult(values=[existing_cheer]),
            ]
        )
        service = module.FeedService(postgres_store=None, xp_service=SimpleNamespace())

        result = await service.send_cheer(
            sender_id=sender_id,
            feed_event_id=existing_cheer.feed_event_id,
            reaction="star",  # different
            postgres_session=session,
        )
        assert result is existing_cheer
        assert existing_cheer.reaction == "star"

    @pytest.mark.asyncio
    async def test_send_cheer_grants_xp_and_notifies_recipient(self, monkeypatch):
        notification_calls = []
        xp_calls = []

        async def fake_notify(patient_id, title, body, data):
            notification_calls.append(
                {
                    "patient_id": patient_id,
                    "title": title,
                    "body": body,
                    "data": data,
                }
            )

        class FakeXPService:
            async def grant_xp(self, **kwargs):
                xp_calls.append(kwargs)
                return (5, 1, False)

        # Stub PatientNameResolver — production now resolves the sender's
        # first name for the notification body.
        class FakeResolver:
            async def resolve_first_name(self, _pid):
                return "Alice"

        module = load_module(
            monkeypatch,
            "lib/services/gamification/feed_service.py",
            "gamification_test_feed_service_success",
            {
                "lib.services.gamification.notifications": make_module(
                    "lib.services.gamification.notifications",
                    send_gamification_notification=fake_notify,
                ),
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=SimpleNamespace(
                        resolve=lambda _cls: FakeResolver(),
                        register=lambda *a, **k: None,
                    ),
                ),
                "lib.ai_foundation.agents.core.patient_resolver": make_module(
                    "lib.ai_foundation.agents.core.patient_resolver",
                    PatientNameResolver=type("PatientNameResolver", (), {}),
                ),
            },
        )
        sender_id = uuid4()
        recipient_id = uuid4()
        event_id = uuid4()
        # Sequence: event lookup → buddy check (yes) → existing cheer (none)
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(feed_id=event_id, actor_id=recipient_id)]),
                FakeScalarResult(scalar=uuid4()),  # buddy_id (truthy = is buddy)
                FakeScalarResult(values=[]),       # no existing cheer
            ]
        )
        service = module.FeedService(postgres_store=None, xp_service=FakeXPService())

        cheer = await service.send_cheer(
            sender_id=sender_id,
            feed_event_id=event_id,
            reaction="applause",
            postgres_session=session,
        )

        assert cheer.sender_id == sender_id
        assert cheer.recipient_id == recipient_id
        assert session.commit_count == 1
        assert xp_calls[0]["amount"] == module.CHEER_XP_REWARD
        assert xp_calls[0]["source_type"] == "cheer"
        # Notification: title fixed, body now includes resolved sender name
        assert len(notification_calls) == 1
        call = notification_calls[0]
        assert call["patient_id"] == str(recipient_id)
        assert call["title"] == "You got a cheer"
        assert "Alice" in call["body"]
        assert call["data"]["event_type"] == "buddy_cheer"
        assert call["data"]["feed_event_id"] == str(event_id)
        assert call["data"]["sender_id"] == str(sender_id)

    @pytest.mark.asyncio
    async def test_enrich_events_masks_identity_outside_group_context(self, monkeypatch):
        async def fake_notify(*_args, **_kwargs):
            return None

        module = load_module(
            monkeypatch,
            "lib/services/gamification/feed_service.py",
            "gamification_test_feed_service_enrich",
            {
                "lib.services.gamification.notifications": make_module(
                    "lib.services.gamification.notifications",
                    send_gamification_notification=fake_notify,
                ),
            },
        )
        viewer_id = uuid4()
        actor_id = uuid4()
        event_id = uuid4()
        event = SimpleNamespace(
            feed_id=event_id,
            actor_id=actor_id,
            event_type="achievement_earned",
            event_data={"slug": "streak_7"},
            created_at=datetime(2026, 4, 3, 8, 0, 0),
        )
        session = FakeSession(
            results=[
                FakeScalarResult(scalar="Alex"),
                FakeScalarResult(scalar="anonymous"),
                FakeScalarResult(scalar=2),
                FakeScalarResult(scalar=None),
            ]
        )
        service = module.FeedService(postgres_store=None, xp_service=SimpleNamespace())

        events = await service._enrich_events(
            [event],
            viewer_id,
            session,
            context="facility",
        )

        assert len(events) == 1
        assert events[0].actor_name == "Anonymous"
        assert events[0].actor_id.startswith("anonymous:")
