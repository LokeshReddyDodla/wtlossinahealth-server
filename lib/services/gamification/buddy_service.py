"""Buddy system — requests, matching, progress sharing."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    Buddy,
    DailyTask,
    PatientAchievement,
    PlayerProfile,
)
from lib.models.patient import Patient
from lib.schemas.gamification import (
    BuddyProgressResponse,
    BuddyResponse,
    TaskStatus,
    title_for_level,
)
from lib.services.gamification.time_utils import local_today
from lib.utils.postgres_session_decorator import with_postgres_session

MAX_ACTIVE_BUDDIES = 3


class BuddyService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    @with_postgres_session
    async def send_request(
        self,
        requester_id: UUID,
        accepter_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> Buddy:
        if requester_id == accepter_id:
            raise ValueError("Cannot buddy yourself")

        # Verify accepter exists and is in the same facility
        accepter_result = await postgres_session.execute(
            select(Patient.patient_id, Patient.health_facility_id).where(
                Patient.patient_id == accepter_id
            )
        )
        accepter_row = accepter_result.first()
        if not accepter_row:
            raise ValueError("Patient not found")

        requester_result = await postgres_session.execute(
            select(Patient.health_facility_id).where(
                Patient.patient_id == requester_id
            )
        )
        requester_facility = requester_result.scalar()
        if requester_facility != accepter_row.health_facility_id:
            raise ValueError("Buddy requests are limited to the same facility")

        active_count = await self._active_buddy_count(
            requester_id, postgres_session
        )
        if active_count >= MAX_ACTIVE_BUDDIES:
            raise ValueError(f"Maximum {MAX_ACTIVE_BUDDIES} active buddies allowed")

        # Check for existing relationship (either direction)
        existing = await postgres_session.execute(
            select(Buddy).where(
                or_(
                    and_(
                        Buddy.requester_id == requester_id,
                        Buddy.accepter_id == accepter_id,
                    ),
                    and_(
                        Buddy.requester_id == accepter_id,
                        Buddy.accepter_id == requester_id,
                    ),
                ),
                Buddy.status.in_(["pending", "active"]),
            )
        )
        if existing.scalars().first():
            raise ValueError("Buddy request already exists")

        buddy = Buddy(requester_id=requester_id, accepter_id=accepter_id)
        postgres_session.add(buddy)
        await postgres_session.commit()
        await postgres_session.refresh(buddy)
        return buddy

    @with_postgres_session
    async def accept_request(
        self,
        buddy_id: UUID,
        accepter_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> Buddy:
        result = await postgres_session.execute(
            select(Buddy).where(
                Buddy.buddy_id == buddy_id,
                Buddy.accepter_id == accepter_id,
                Buddy.status == "pending",
            )
        )
        buddy = result.scalars().first()
        if not buddy:
            raise ValueError("Buddy request not found")

        active_count = await self._active_buddy_count(
            accepter_id, postgres_session
        )
        if active_count >= MAX_ACTIVE_BUDDIES:
            raise ValueError(f"Maximum {MAX_ACTIVE_BUDDIES} active buddies allowed")

        buddy.status = "active"
        buddy.accepted_at = datetime.now().replace(tzinfo=None)
        await postgres_session.commit()
        await postgres_session.refresh(buddy)
        return buddy

    @with_postgres_session
    async def remove_buddy(
        self,
        buddy_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        result = await postgres_session.execute(
            select(Buddy).where(
                Buddy.buddy_id == buddy_id,
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
                Buddy.status == "active",
            )
        )
        buddy = result.scalars().first()
        if not buddy:
            raise ValueError("Buddy not found")

        buddy.status = "removed"
        buddy.removed_at = datetime.now().replace(tzinfo=None)
        buddy.removed_by = patient_id
        await postgres_session.commit()

    @with_postgres_session
    async def get_buddies(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[BuddyResponse]:
        result = await postgres_session.execute(
            select(Buddy).where(
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
                Buddy.status.in_(["pending", "active"]),
            )
        )
        buddies = result.scalars().all()

        responses = []
        for b in buddies:
            other_id = (
                b.accepter_id if b.requester_id == patient_id else b.requester_id
            )
            name_result = await postgres_session.execute(
                select(Patient.first_name).where(
                    Patient.patient_id == other_id
                )
            )
            name = name_result.scalar()

            responses.append(
                BuddyResponse(
                    buddy_id=str(b.buddy_id),
                    buddy_patient_id=str(other_id),
                    buddy_name=name,
                    status=b.status,
                    buddy_streak=b.buddy_streak,
                    buddy_streak_longest=b.buddy_streak_longest,
                    created_at=b.created_at,
                    accepted_at=b.accepted_at,
                )
            )
        return responses

    @with_postgres_session
    async def get_buddy_progress(
        self,
        buddy_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> BuddyProgressResponse:
        result = await postgres_session.execute(
            select(Buddy).where(
                Buddy.buddy_id == buddy_id,
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
                Buddy.status == "active",
            )
        )
        buddy = result.scalars().first()
        if not buddy:
            raise ValueError("Buddy not found")

        other_id = (
            buddy.accepter_id
            if buddy.requester_id == patient_id
            else buddy.requester_id
        )

        # Get buddy's profile
        profile_result = await postgres_session.execute(
            select(PlayerProfile).where(PlayerProfile.patient_id == other_id)
        )
        profile = profile_result.scalars().first()

        # Get buddy's name
        name_result = await postgres_session.execute(
            select(Patient.first_name).where(Patient.patient_id == other_id)
        )
        name = name_result.scalar()

        # Get today's task stats in the buddy's local timezone
        tz_result = await postgres_session.execute(
            select(Patient.locale).where(Patient.patient_id == other_id)
        )
        today = local_today(tz_result.scalar())
        task_result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == other_id,
                DailyTask.task_date == today,
            )
        )
        tasks = task_result.scalars().all()
        completed = sum(
            1 for t in tasks if t.status == TaskStatus.COMPLETED.value
        )

        # Recent achievements (last 5 slugs)
        ach_result = await postgres_session.execute(
            select(PatientAchievement)
            .where(PatientAchievement.patient_id == other_id)
            .order_by(PatientAchievement.earned_at.desc())
            .limit(5)
        )
        from lib.models.gamification import Achievement

        recent_slugs = []
        for pa in ach_result.scalars().all():
            a_result = await postgres_session.execute(
                select(Achievement.slug).where(
                    Achievement.achievement_id == pa.achievement_id
                )
            )
            slug = a_result.scalar()
            if slug:
                recent_slugs.append(slug)

        return BuddyProgressResponse(
            buddy_patient_id=str(other_id),
            buddy_name=name,
            level=profile.level if profile else 1,
            title=title_for_level(profile.level if profile else 1),
            current_streak=profile.current_streak if profile else 0,
            tasks_completed_today=completed,
            tasks_total_today=len(tasks),
            recent_achievements=recent_slugs,
        )

    async def _active_buddy_count(
        self, patient_id: UUID, session: AsyncSession
    ) -> int:
        result = await session.execute(
            select(func.count(Buddy.buddy_id)).where(
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
                Buddy.status == "active",
            )
        )
        return result.scalar() or 0
