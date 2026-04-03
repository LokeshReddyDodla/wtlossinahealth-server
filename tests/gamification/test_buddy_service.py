from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module


class TestBuddyService:
    @pytest.mark.asyncio
    async def test_send_request_creates_pending_buddy_when_same_facility(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/buddy_service.py",
            "gamification_test_buddy_service_send",
        )
        service = module.BuddyService(postgres_store=None)
        requester_id = uuid4()
        accepter_id = uuid4()
        facility_id = uuid4()

        async def fake_active_count(_patient_id, _session):
            return 1

        monkeypatch.setattr(service, "_active_buddy_count", fake_active_count)
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(patient_id=accepter_id, health_facility_id=facility_id)]),
                FakeScalarResult(scalar=facility_id),
                FakeScalarResult(scalar=0),
                FakeScalarResult(values=[]),
            ]
        )

        buddy = await service.send_request(
            requester_id=requester_id,
            accepter_id=accepter_id,
            postgres_session=session,
        )

        assert buddy.requester_id == requester_id
        assert buddy.accepter_id == accepter_id
        assert session.commit_count == 1
        assert session.refresh_count == 1

    @pytest.mark.asyncio
    async def test_send_request_rejects_different_facility(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/buddy_service.py",
            "gamification_test_buddy_service_facility",
        )
        service = module.BuddyService(postgres_store=None)

        async def fake_active_count(_patient_id, _session):
            return 0

        monkeypatch.setattr(service, "_active_buddy_count", fake_active_count)
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(health_facility_id=uuid4())]),
                FakeScalarResult(scalar=uuid4()),
            ]
        )

        with pytest.raises(ValueError, match="same facility"):
            await service.send_request(
                requester_id=uuid4(),
                accepter_id=uuid4(),
                postgres_session=session,
            )

    @pytest.mark.asyncio
    async def test_send_request_rejects_existing_relationship(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/buddy_service.py",
            "gamification_test_buddy_service_existing",
        )
        service = module.BuddyService(postgres_store=None)
        facility_id = uuid4()

        async def fake_active_count(_patient_id, _session):
            return 0

        monkeypatch.setattr(service, "_active_buddy_count", fake_active_count)
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(health_facility_id=facility_id)]),
                FakeScalarResult(scalar=facility_id),
                FakeScalarResult(scalar=0),
                FakeScalarResult(values=[SimpleNamespace(status="active")]),
            ]
        )

        with pytest.raises(ValueError, match="already exists"):
            await service.send_request(
                requester_id=uuid4(),
                accepter_id=uuid4(),
                postgres_session=session,
            )

    @pytest.mark.asyncio
    async def test_accept_request_rejects_when_accepter_has_max_buddies(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/buddy_service.py",
            "gamification_test_buddy_service_accept_limit",
        )
        service = module.BuddyService(postgres_store=None)

        async def fake_active_count(_patient_id, _session):
            return module.MAX_ACTIVE_BUDDIES

        monkeypatch.setattr(service, "_active_buddy_count", fake_active_count)
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(status="pending", accepter_id=uuid4())]),
            ]
        )

        with pytest.raises(ValueError, match="Maximum 3 active buddies allowed"):
            await service.accept_request(
                buddy_id=uuid4(),
                accepter_id=uuid4(),
                postgres_session=session,
            )

    @pytest.mark.asyncio
    async def test_get_buddy_progress_uses_buddy_local_date(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/buddy_service.py",
            "gamification_test_buddy_service_progress",
        )
        service = module.BuddyService(postgres_store=None)
        patient_id = uuid4()
        other_id = uuid4()
        buddy = SimpleNamespace(
            requester_id=patient_id,
            accepter_id=other_id,
            status="active",
        )
        profile = SimpleNamespace(level=10, current_streak=8)
        task_completed = SimpleNamespace(status="completed")
        task_pending = SimpleNamespace(status="pending")
        # Joined query returns rows with .Achievement.slug
        ach_row = SimpleNamespace(
            Achievement=SimpleNamespace(slug="streak_7"),
        )
        session = FakeSession(
            results=[
                FakeScalarResult(values=[buddy]),
                FakeScalarResult(values=[profile]),
                FakeScalarResult(scalar="Mina"),
                FakeScalarResult(scalar="America/New_York"),
                FakeScalarResult(values=[task_completed, task_pending]),
                FakeScalarResult(values=[ach_row]),
            ]
        )
        monkeypatch.setattr(module, "local_today", lambda _tz=None: date(2026, 4, 2))

        progress = await service.get_buddy_progress(
            buddy_id=uuid4(),
            patient_id=patient_id,
            postgres_session=session,
        )

        assert progress.buddy_name == "Mina"
        assert progress.level == 10
        assert progress.tasks_completed_today == 1
        assert progress.tasks_total_today == 2
        assert progress.recent_achievements == ["streak_7"]
