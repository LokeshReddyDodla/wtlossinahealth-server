from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module


class TestGroupService:
    @pytest.mark.asyncio
    async def test_create_group_auto_adds_patient_creator_as_admin(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_create",
        )
        service = module.GroupService(postgres_store=None)
        creator_id = uuid4()
        session = FakeSession()

        group = await service.create_group(
            name="Founders",
            group_type="patient_created",
            created_by_id=creator_id,
            created_by_type="patient",
            postgres_session=session,
        )

        assert group.name == "Founders"
        assert len(session.added) == 2
        assert session.added[1].patient_id == creator_id
        assert session.added[1].role == "admin"
        assert session.commit_count == 2

    @pytest.mark.asyncio
    async def test_join_group_reactivates_existing_inactive_member(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_rejoin",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(group_id=uuid4(), is_active=True, max_members=10)
        member = SimpleNamespace(
            is_active=False,
            left_at=datetime(2026, 4, 1, 10, 0, 0),
            joined_at=None,
        )

        async def fake_get_group(_group_id, _session):
            return group

        async def fake_member_count(_group_id, _session):
            return 2

        monkeypatch.setattr(service, "_get_group", fake_get_group)
        monkeypatch.setattr(service, "_member_count", fake_member_count)
        session = FakeSession(results=[FakeScalarResult(values=[member])])

        result = await service.join_group(
            group_id=group.group_id,
            patient_id=uuid4(),
            postgres_session=session,
        )

        assert result is member
        assert member.is_active is True
        assert member.left_at is None
        assert member.joined_at is not None
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_join_group_rejects_when_group_is_full(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_full",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(group_id=uuid4(), is_active=True, max_members=2)

        async def fake_get_group(_group_id, _session):
            return group

        async def fake_member_count(_group_id, _session):
            return 2

        monkeypatch.setattr(service, "_get_group", fake_get_group)
        monkeypatch.setattr(service, "_member_count", fake_member_count)

        with pytest.raises(ValueError, match="Group is full"):
            await service.join_group(
                group_id=group.group_id,
                patient_id=uuid4(),
                postgres_session=FakeSession(),
            )

    @pytest.mark.asyncio
    async def test_leave_group_marks_membership_inactive(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_leave",
        )
        service = module.GroupService(postgres_store=None)
        member = SimpleNamespace(is_active=True, left_at=None)
        session = FakeSession(results=[FakeScalarResult(values=[member])])

        await service.leave_group(
            group_id=uuid4(),
            patient_id=uuid4(),
            postgres_session=session,
        )

        assert member.is_active is False
        assert member.left_at is not None
        assert session.commit_count == 1
