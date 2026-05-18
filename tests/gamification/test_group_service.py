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

        # Short-circuit invite code generation (it queries the session)
        async def fake_invite(_session):
            return "TESTCD"
        monkeypatch.setattr(module.GroupService, "_generate_invite_code", staticmethod(fake_invite))

        session = FakeSession()

        group = await service.create_group(
            name="Founders",
            group_type="patient_created",
            created_by_id=creator_id,
            created_by_type="patient",
            postgres_session=session,
        )

        assert group.name == "Founders"
        assert group.invite_code == "TESTCD"
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
        # facility_id=None skips the facility-scope check that would otherwise
        # fire an extra query.
        group = SimpleNamespace(
            group_id=uuid4(), is_active=True, max_members=10, facility_id=None,
        )
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
        group = SimpleNamespace(
            group_id=uuid4(), is_active=True, max_members=2, facility_id=None,
        )

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
    async def test_update_group_changes_name_and_description(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_update",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(
            group_id=uuid4(), is_active=True, name="Old", description="Old desc", max_members=20,
        )

        async def fake_get_group(_group_id, _session):
            return group

        async def fake_member_count(_group_id, _session):
            return 5

        monkeypatch.setattr(service, "_get_group", fake_get_group)
        monkeypatch.setattr(service, "_member_count", fake_member_count)
        monkeypatch.setattr(
            module.GroupService, "to_response",
            staticmethod(lambda g, c: SimpleNamespace(group_id=str(g.group_id), name=g.name, description=g.description, member_count=c)),
        )

        result = await service.update_group(
            group.group_id, name="New", description="New desc",
            postgres_session=FakeSession(),
        )

        assert group.name == "New"
        assert group.description == "New desc"
        assert result.name == "New"
        assert result.member_count == 5

    @pytest.mark.asyncio
    async def test_update_group_rejects_max_members_below_current_count(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_update_shrink",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(
            group_id=uuid4(), is_active=True, name="X", description="", max_members=20,
        )

        async def fake_get_group(_gid, _s):
            return group

        async def fake_count(_gid, _s):
            return 10

        monkeypatch.setattr(service, "_get_group", fake_get_group)
        monkeypatch.setattr(service, "_member_count", fake_count)

        with pytest.raises(ValueError, match="cannot be less than current member count"):
            await service.update_group(
                group.group_id, max_members=5, postgres_session=FakeSession(),
            )

    @pytest.mark.asyncio
    async def test_update_group_rejects_inactive_group(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_update_inactive",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(group_id=uuid4(), is_active=False)

        async def fake_get_group(_gid, _s):
            return group

        monkeypatch.setattr(service, "_get_group", fake_get_group)

        with pytest.raises(ValueError, match="not found or inactive"):
            await service.update_group(
                group.group_id, name="X", postgres_session=FakeSession(),
            )

    @pytest.mark.asyncio
    async def test_delete_group_deactivates_group_and_members(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_delete",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(group_id=uuid4(), is_active=True)
        members = [
            SimpleNamespace(is_active=True, left_at=None),
            SimpleNamespace(is_active=True, left_at=None),
        ]

        async def fake_get_group(_gid, _s):
            return group

        monkeypatch.setattr(service, "_get_group", fake_get_group)
        session = FakeSession(results=[FakeScalarResult(values=members)])

        await service.delete_group(group.group_id, postgres_session=session)

        assert group.is_active is False
        assert all(m.is_active is False for m in members)
        assert all(m.left_at is not None for m in members)
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_delete_group_is_noop_on_already_inactive(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_delete_noop",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(group_id=uuid4(), is_active=False)

        async def fake_get_group(_gid, _s):
            return group

        monkeypatch.setattr(service, "_get_group", fake_get_group)
        session = FakeSession()

        await service.delete_group(group.group_id, postgres_session=session)
        assert session.commit_count == 0

    @pytest.mark.asyncio
    async def test_delete_group_raises_if_not_found(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_delete_missing",
        )
        service = module.GroupService(postgres_store=None)

        async def fake_get_group(_gid, _s):
            return None

        monkeypatch.setattr(service, "_get_group", fake_get_group)

        with pytest.raises(ValueError, match="Group not found"):
            await service.delete_group(uuid4(), postgres_session=FakeSession())

    @pytest.mark.asyncio
    async def test_remove_member_marks_inactive(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_remove_member",
        )
        service = module.GroupService(postgres_store=None)
        member = SimpleNamespace(is_active=True, left_at=None)
        session = FakeSession(results=[FakeScalarResult(values=[member])])

        await service.remove_member(uuid4(), uuid4(), postgres_session=session)

        assert member.is_active is False
        assert member.left_at is not None
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_remove_member_raises_when_not_a_member(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_remove_member_missing",
        )
        service = module.GroupService(postgres_store=None)
        session = FakeSession(results=[FakeScalarResult(values=[])])

        with pytest.raises(ValueError, match="not an active member"):
            await service.remove_member(uuid4(), uuid4(), postgres_session=session)

    @pytest.mark.asyncio
    async def test_rotate_invite_code_generates_new_code(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_rotate",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(group_id=uuid4(), is_active=True, invite_code="OLD123")

        async def fake_get_group(_gid, _s):
            return group

        async def fake_invite(_session):
            return "NEWCODE"

        monkeypatch.setattr(service, "_get_group", fake_get_group)
        monkeypatch.setattr(module.GroupService, "_generate_invite_code", staticmethod(fake_invite))

        new_code = await service.rotate_invite_code(group.group_id, postgres_session=FakeSession())

        assert new_code == "NEWCODE"
        assert group.invite_code == "NEWCODE"

    @pytest.mark.asyncio
    async def test_rotate_invite_code_rejects_inactive(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_rotate_inactive",
        )
        service = module.GroupService(postgres_store=None)
        group = SimpleNamespace(group_id=uuid4(), is_active=False)

        async def fake_get_group(_gid, _s):
            return group

        monkeypatch.setattr(service, "_get_group", fake_get_group)

        with pytest.raises(ValueError, match="not found or inactive"):
            await service.rotate_invite_code(group.group_id, postgres_session=FakeSession())

    @pytest.mark.asyncio
    async def test_leave_group_marks_membership_inactive(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/group_service.py",
            "gamification_test_group_service_leave",
        )
        service = module.GroupService(postgres_store=None)
        member = SimpleNamespace(is_active=True, left_at=None)
        # leave_group now also queries for active group challenges to expire
        # tasks for. Provide an empty result for that follow-up query.
        session = FakeSession(results=[
            FakeScalarResult(values=[member]),
            FakeScalarResult(values=[]),
        ])

        await service.leave_group(
            group_id=uuid4(),
            patient_id=uuid4(),
            postgres_session=session,
        )

        assert member.is_active is False
        assert member.left_at is not None
        assert session.commit_count >= 1
