from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module, make_module


class TestGamificationService:
    @pytest.mark.asyncio
    async def test_use_streak_freeze_defaults_to_patient_local_date(self, monkeypatch):
        calls = []

        class FakeStreakService:
            async def use_freeze(self, patient_id, freeze_date, **kwargs):
                calls.append(
                    {
                        "patient_id": patient_id,
                        "freeze_date": freeze_date,
                        "postgres_session": kwargs.get("postgres_session"),
                    }
                )

        class FakeContainer:
            def resolve(self, _cls):
                return FakeStreakService()

        module = load_module(
            monkeypatch,
            "lib/services/gamification/service.py",
            "gamification_test_service_freeze",
            {
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
            },
        )
        service = module.GamificationService(
            postgres_store=None,
            xp_service=SimpleNamespace(),
            task_generator=SimpleNamespace(),
            achievement_evaluator=SimpleNamespace(),
        )
        patient_id = uuid4()
        session = FakeSession()

        async def fake_patient_today(_patient_id, _session):
            return date(2026, 4, 3)

        async def fake_get_or_create_profile(_patient_id, **_kwargs):
            return "profile-response"

        monkeypatch.setattr(service, "_patient_today", fake_patient_today)
        monkeypatch.setattr(service, "get_or_create_profile", fake_get_or_create_profile)

        result = await service.use_streak_freeze(
            patient_id=patient_id,
            postgres_session=session,
        )

        assert result == "profile-response"
        assert calls == [
            {
                "patient_id": patient_id,
                "freeze_date": date(2026, 4, 3),
                "postgres_session": session,
            }
        ]

    @pytest.mark.asyncio
    async def test_post_feed_event_posts_and_notifies_for_supported_event(
        self,
        monkeypatch,
    ):
        feed_calls = []
        notification_calls = []

        class FakeFeedService:
            async def post_event(self, **kwargs):
                feed_calls.append(kwargs)

        class FakeContainer:
            def resolve(self, _cls):
                return FakeFeedService()

        async def fake_notify(patient_id, title, body, data):
            notification_calls.append(
                {
                    "patient_id": patient_id,
                    "title": title,
                    "body": body,
                    "data": data,
                }
            )

        module = load_module(
            monkeypatch,
            "lib/services/gamification/service.py",
            "gamification_test_service_feed",
            {
                "lib.core.container": make_module(
                    "lib.core.container",
                    container=FakeContainer(),
                ),
                "lib.services.gamification.feed_service": make_module(
                    "lib.services.gamification.feed_service",
                    FeedService=type("FeedService", (), {}),
                ),
                "lib.services.gamification.notifications": make_module(
                    "lib.services.gamification.notifications",
                    send_gamification_notification=fake_notify,
                ),
            },
        )
        service = module.GamificationService(
            postgres_store=None,
            xp_service=SimpleNamespace(),
            task_generator=SimpleNamespace(),
            achievement_evaluator=SimpleNamespace(),
        )
        patient_id = uuid4()

        await service._post_feed_event(
            patient_id,
            "level_up",
            {"new_level": 20},
        )

        assert feed_calls == [
            {
                "actor_id": patient_id,
                "event_type": "level_up",
                "event_data": {"new_level": 20},
                "visibility": "group",
            }
        ]
        assert notification_calls == [
            {
                "patient_id": str(patient_id),
                "title": "Level up",
                "body": "You reached level 20.",
                "data": {"event_type": "level_up", "new_level": 20},
            }
        ]

    @pytest.mark.asyncio
    async def test_get_recent_achievements_sorts_and_limits(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/service.py",
            "gamification_test_service_recent_achievements",
        )
        service = module.GamificationService(
            postgres_store=None,
            xp_service=SimpleNamespace(),
            task_generator=SimpleNamespace(),
            achievement_evaluator=SimpleNamespace(),
        )
        achievements = [
            SimpleNamespace(earned=True, earned_at=datetime(2026, 4, 1, 10, 0, 0), slug="old"),
            SimpleNamespace(earned=False, earned_at=None, slug="hidden"),
            SimpleNamespace(earned=True, earned_at=datetime(2026, 4, 3, 10, 0, 0), slug="newest"),
            SimpleNamespace(earned=True, earned_at=datetime(2026, 4, 2, 10, 0, 0), slug="middle"),
        ]

        async def fake_get_achievements(_patient_id, **_kwargs):
            return achievements

        monkeypatch.setattr(service, "get_achievements", fake_get_achievements)

        recent = await service.get_recent_achievements(uuid4(), limit=2, postgres_session=FakeSession())

        assert [item.slug for item in recent] == ["newest", "middle"]

    @pytest.mark.asyncio
    async def test_get_gamification_context_includes_group_and_direct_challenges(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/service.py",
            "gamification_test_service_context",
        )
        service = module.GamificationService(
            postgres_store=None,
            xp_service=SimpleNamespace(),
            task_generator=SimpleNamespace(),
            achievement_evaluator=SimpleNamespace(),
        )
        patient_id = uuid4()
        group_id = uuid4()
        profile = SimpleNamespace(
            level=12,
            total_xp=5400,
            current_streak=14,
            streak_freezes=2,
        )
        direct = SimpleNamespace(
            ChallengeParticipant=SimpleNamespace(current_value=20000, rank=2),
            Challenge=SimpleNamespace(title="Solo Sprint", target_value=50000),
        )
        group = SimpleNamespace(
            ChallengeParticipant=SimpleNamespace(current_value=62000, rank=1),
            Challenge=SimpleNamespace(title="Team Steps", target_value=100000),
        )
        session = FakeSession(
            results=[
                FakeScalarResult(values=[profile]),
                FakeScalarResult(values=[SimpleNamespace(Achievement=SimpleNamespace(slug="streak_14"))]),
                FakeScalarResult(
                    values=[
                        SimpleNamespace(status="completed"),
                        SimpleNamespace(status="pending"),
                    ]
                ),
                FakeScalarResult(
                    values=[
                        SimpleNamespace(
                            title="Meal Tracker",
                            current_value=3,
                            target_value=5,
                            status="active",
                        )
                    ]
                ),
                FakeScalarResult(scalar=8),
                FakeScalarResult(values=[direct]),
                FakeScalarResult(values=[group_id]),
                FakeScalarResult(values=[group]),
            ]
        )

        async def fake_patient_today(_patient_id, _session):
            return date(2026, 4, 3)

        monkeypatch.setattr(service, "_patient_today", fake_patient_today)

        context = await service.get_gamification_context(
            patient_id=patient_id,
            postgres_session=session,
        )

        assert context.level == 12
        assert context.recent_achievements == ["streak_14"]
        assert context.tasks_today == {"completed": 1, "total": 2}
        assert context.weekly_quest == {
            "title": "Meal Tracker",
            "progress": "3/5",
            "status": "active",
        }
        assert context.buddy_streak == 8
        assert context.active_challenges == [
            {"title": "Solo Sprint", "rank": 2, "progress": "20000/50000"},
            {"title": "Team Steps", "rank": 1, "progress": "62000/100000"},
        ]
