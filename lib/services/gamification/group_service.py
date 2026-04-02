"""Group management — CRUD, membership, stats."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import Group, GroupMember, PlayerProfile
from lib.models.patient import Patient
from lib.schemas.gamification import (
    GroupMemberResponse,
    GroupResponse,
    title_for_level,
)
from lib.utils.postgres_session_decorator import with_postgres_session


class GroupService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def create_group(
        self,
        name: str,
        group_type: str,
        created_by_id: UUID,
        created_by_type: str,
        *,
        description: Optional[str] = None,
        facility_id: Optional[UUID] = None,
        max_members: int = 50,
        postgres_session: AsyncSession,
    ) -> Group:
        group = Group(
            name=name,
            description=description,
            group_type=group_type,
            created_by_id=created_by_id,
            created_by_type=created_by_type,
            facility_id=facility_id,
            max_members=max_members,
        )
        postgres_session.add(group)
        await postgres_session.commit()
        await postgres_session.refresh(group)

        # Auto-add creator as admin if they're a patient
        if created_by_type == "patient":
            member = GroupMember(
                group_id=group.group_id,
                patient_id=created_by_id,
                role="admin",
            )
            postgres_session.add(member)
            await postgres_session.commit()

        return group

    @with_postgres_session
    async def join_group(
        self,
        group_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> GroupMember:
        group = await self._get_group(group_id, postgres_session)
        if not group or not group.is_active:
            raise ValueError("Group not found or inactive")

        # Check member count
        count = await self._member_count(group_id, postgres_session)
        if count >= group.max_members:
            raise ValueError("Group is full")

        # Check if already a member
        existing = await postgres_session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.patient_id == patient_id,
            )
        )
        member = existing.scalars().first()
        if member:
            if member.is_active:
                raise ValueError("Already a member")
            member.is_active = True
            member.left_at = None
            member.joined_at = datetime.now().replace(tzinfo=None)
        else:
            member = GroupMember(
                group_id=group_id, patient_id=patient_id
            )
            postgres_session.add(member)

        await postgres_session.commit()
        await postgres_session.refresh(member)
        return member

    @with_postgres_session
    async def leave_group(
        self,
        group_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        result = await postgres_session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.patient_id == patient_id,
                GroupMember.is_active == True,
            )
        )
        member = result.scalars().first()
        if not member:
            raise ValueError("Not a member of this group")

        member.is_active = False
        member.left_at = datetime.now().replace(tzinfo=None)
        await postgres_session.commit()

    @with_postgres_session
    async def get_group(
        self,
        group_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[GroupResponse]:
        group = await self._get_group(group_id, postgres_session)
        if not group:
            return None
        count = await self._member_count(group_id, postgres_session)
        return self._to_response(group, count)

    @with_postgres_session
    async def get_patient_groups(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[GroupResponse]:
        result = await postgres_session.execute(
            select(GroupMember.group_id).where(
                GroupMember.patient_id == patient_id,
                GroupMember.is_active == True,
            )
        )
        group_ids = result.scalars().all()
        if not group_ids:
            return []

        groups_result = await postgres_session.execute(
            select(Group).where(
                Group.group_id.in_(group_ids), Group.is_active == True
            )
        )
        groups = groups_result.scalars().all()

        responses = []
        for g in groups:
            count = await self._member_count(g.group_id, postgres_session)
            responses.append(self._to_response(g, count))
        return responses

    @with_postgres_session
    async def get_members(
        self,
        group_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[GroupMemberResponse]:
        result = await postgres_session.execute(
            select(GroupMember, Patient, PlayerProfile)
            .join(Patient, GroupMember.patient_id == Patient.patient_id)
            .outerjoin(
                PlayerProfile,
                GroupMember.patient_id == PlayerProfile.patient_id,
            )
            .where(
                GroupMember.group_id == group_id,
                GroupMember.is_active == True,
            )
        )
        rows = result.all()

        return [
            GroupMemberResponse(
                patient_id=str(row.GroupMember.patient_id),
                patient_name=row.Patient.first_name,
                role=row.GroupMember.role,
                level=row.PlayerProfile.level if row.PlayerProfile else 1,
                title=title_for_level(
                    row.PlayerProfile.level if row.PlayerProfile else 1
                ),
                current_streak=(
                    row.PlayerProfile.current_streak
                    if row.PlayerProfile
                    else 0
                ),
                joined_at=row.GroupMember.joined_at,
            )
            for row in rows
        ]

    async def _get_group(
        self, group_id: UUID, session: AsyncSession
    ) -> Optional[Group]:
        result = await session.execute(
            select(Group).where(Group.group_id == group_id)
        )
        return result.scalars().first()

    async def _member_count(
        self, group_id: UUID, session: AsyncSession
    ) -> int:
        result = await session.execute(
            select(func.count(GroupMember.id)).where(
                GroupMember.group_id == group_id,
                GroupMember.is_active == True,
            )
        )
        return result.scalar() or 0

    def _to_response(self, group: Group, member_count: int) -> GroupResponse:
        return GroupResponse(
            group_id=str(group.group_id),
            name=group.name,
            description=group.description,
            group_type=group.group_type,
            created_by_id=str(group.created_by_id),
            created_by_type=group.created_by_type,
            facility_id=str(group.facility_id) if group.facility_id else None,
            member_count=member_count,
            max_members=group.max_members,
            is_active=group.is_active,
            created_at=group.created_at,
        )
