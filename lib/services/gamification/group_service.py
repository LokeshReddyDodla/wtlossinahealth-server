"""Group management — CRUD, membership, stats."""

from __future__ import annotations

import secrets
import string
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
            invite_code=await self._generate_invite_code(postgres_session),
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

        # Facility-scoped groups: patient must belong to the same facility
        if group.facility_id:
            facility_result = await postgres_session.execute(
                select(Patient.health_facility_id).where(
                    Patient.patient_id == patient_id
                )
            )
            patient_facility = facility_result.scalar()
            if patient_facility != group.facility_id:
                raise ValueError("This group is restricted to patients of a specific facility")

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

        # Expire today's challenge tasks for group challenges the patient was in
        from lib.models.gamification import Challenge, ChallengeParticipant, DailyTask
        from lib.services.gamification.time_utils import local_today
        today = local_today(None)

        # Find active group challenges
        challenge_result = await postgres_session.execute(
            select(Challenge.challenge_id).join(
                ChallengeParticipant,
                ChallengeParticipant.challenge_id == Challenge.challenge_id,
            ).where(
                ChallengeParticipant.participant_id == group_id,
                ChallengeParticipant.participant_type == "group",
                ChallengeParticipant.status == "active",
                Challenge.is_active == True,
            )
        )
        for row in challenge_result.all():
            task_type = f"CHALLENGE_TASK_{row.challenge_id.hex}"
            task_result = await postgres_session.execute(
                select(DailyTask).where(
                    DailyTask.patient_id == patient_id,
                    DailyTask.task_date == today,
                    DailyTask.task_type == task_type,
                    DailyTask.status == "pending",
                )
            )
            for task in task_result.scalars().all():
                task.status = "expired"

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
        return self.to_response(group, count)

    @with_postgres_session
    async def get_group_info(
        self,
        invite_code: str,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ):
        """Rich group info by invite_code — avatar, your role, top member previews."""
        from lib.schemas.gamification import GroupInfoResponse, GroupMemberPreview
        from lib.models.patient import Patient

        # Resolve invite_code → group
        group_result = await postgres_session.execute(
            select(Group).where(Group.invite_code == invite_code.upper().strip())
        )
        group = group_result.scalars().first()
        if not group:
            return None
        group_id = group.group_id

        # Facility-scoped groups: only patients of that facility can preview
        if group.facility_id:
            facility_result = await postgres_session.execute(
                select(Patient.health_facility_id).where(
                    Patient.patient_id == patient_id
                )
            )
            patient_facility = facility_result.scalar()
            if patient_facility != group.facility_id:
                return None  # treated as 404 by the endpoint

        count = await self._member_count(group_id, postgres_session)

        # Patient's role in this group (if member)
        role_result = await postgres_session.execute(
            select(GroupMember.role).where(
                GroupMember.group_id == group_id,
                GroupMember.patient_id == patient_id,
                GroupMember.is_active == True,
            )
        )
        your_role = role_result.scalar()

        # Top 5 members (admins first, then members) with profile info
        members_result = await postgres_session.execute(
            select(
                GroupMember.patient_id,
                GroupMember.role,
                Patient.first_name,
                Patient.profile_picture,
            )
            .join(Patient, Patient.patient_id == GroupMember.patient_id)
            .where(
                GroupMember.group_id == group_id,
                GroupMember.is_active == True,
            )
            .order_by(GroupMember.role.desc(), GroupMember.joined_at.asc())
            .limit(5)
        )
        top_members = [
            GroupMemberPreview(
                patient_id=str(row.patient_id),
                first_name=row.first_name,
                profile_picture=row.profile_picture,
                role=row.role or "member",
            )
            for row in members_result.all()
        ]

        return GroupInfoResponse(
            group_id=str(group.group_id),
            name=group.name,
            description=group.description,
            avatar_url=group.avatar_url,
            group_type=group.group_type,
            member_count=count,
            max_members=group.max_members,
            is_active=group.is_active,
            invite_code=group.invite_code,
            your_role=your_role,  # null if not a member (preview mode)
            top_members=top_members,
            created_at=group.created_at,
        )

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
            responses.append(self.to_response(g, count))
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

    @with_postgres_session
    async def add_members(
        self,
        group_id: UUID,
        patient_ids: List[UUID],
        *,
        postgres_session: AsyncSession,
    ) -> int:
        """Add multiple patients to a group. Skips already-active members.
        Returns the number of newly added members."""
        group = await self._get_group(group_id, postgres_session)
        if not group or not group.is_active:
            raise ValueError("Group not found or inactive")

        count = await self._member_count(group_id, postgres_session)
        available = group.max_members - count
        added = 0

        for pid in patient_ids:
            if added >= available:
                break

            existing = await postgres_session.execute(
                select(GroupMember).where(
                    GroupMember.group_id == group_id,
                    GroupMember.patient_id == pid,
                )
            )
            member = existing.scalars().first()
            if member:
                if member.is_active:
                    continue
                member.is_active = True
                member.left_at = None
                member.joined_at = datetime.now().replace(tzinfo=None)
            else:
                postgres_session.add(
                    GroupMember(group_id=group_id, patient_id=pid)
                )
            added += 1

        await postgres_session.commit()
        return added

    @with_postgres_session
    async def join_by_code(
        self,
        invite_code: str,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> GroupResponse:
        """Look up a group by invite code and join it."""
        result = await postgres_session.execute(
            select(Group).where(
                Group.invite_code == invite_code.upper(),
                Group.is_active == True,
            )
        )
        group = result.scalars().first()
        if not group:
            raise ValueError("Invalid or expired invite code")

        # Reuse join_group for all membership checks (capacity, duplicates)
        await self.join_group(group.group_id, patient_id)
        count = await self._member_count(group.group_id, postgres_session)
        return self.to_response(group, count)

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

    @staticmethod
    async def _generate_invite_code(session: AsyncSession) -> str:
        """Generate a unique 6-char alphanumeric invite code (no 0/O/1/I)."""
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        for _ in range(10):
            code = "".join(secrets.choice(alphabet) for _ in range(6))
            existing = await session.execute(
                select(Group.group_id).where(Group.invite_code == code)
            )
            if not existing.scalars().first():
                return code
        raise RuntimeError("Failed to generate unique invite code")

    @staticmethod
    def to_response(group: Group, member_count: int) -> GroupResponse:
        return GroupResponse(
            group_id=str(group.group_id),
            name=group.name,
            description=group.description,
            group_type=group.group_type,
            created_by_id=str(group.created_by_id),
            created_by_type=group.created_by_type,
            facility_id=str(group.facility_id) if group.facility_id else None,
            invite_code=group.invite_code,
            avatar_url=group.avatar_url,
            member_count=member_count,
            max_members=group.max_members,
            is_active=group.is_active,
            created_at=group.created_at,
        )
