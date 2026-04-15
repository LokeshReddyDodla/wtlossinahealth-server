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
from lib.schemas.gamification import MAX_ACTIVE_BUDDIES
from lib.services.gamification.notifications import send_gamification_notification
from lib.services.gamification.time_utils import local_today
from lib.utils.postgres_session_decorator import with_postgres_session


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

        # Rate limit: max BUDDY_REQUESTS_PER_DAY per day
        from lib.schemas.gamification import BUDDY_REQUESTS_PER_DAY
        from lib.services.gamification.time_utils import get_patient_timezone, local_today, naive_day_bounds_for_local_date
        tz_name = await get_patient_timezone(requester_id, postgres_session)
        day_start, _ = naive_day_bounds_for_local_date(local_today(tz_name), tz_name)
        daily_requests = await postgres_session.execute(
            select(func.count(Buddy.buddy_id)).where(
                Buddy.requester_id == requester_id,
                Buddy.created_at >= day_start,
            )
        )
        if (daily_requests.scalar() or 0) >= BUDDY_REQUESTS_PER_DAY:
            raise ValueError(f"Maximum {BUDDY_REQUESTS_PER_DAY} buddy requests per day")

        active_count = await self._active_buddy_count(
            requester_id, postgres_session
        )
        if active_count >= MAX_ACTIVE_BUDDIES:
            raise ValueError(f"Maximum {MAX_ACTIVE_BUDDIES} active buddies allowed")

        # Check for existing relationship (either direction, any status)
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
            )
        )
        existing_buddy = existing.scalars().first()
        if existing_buddy:
            if existing_buddy.status in ("pending", "active"):
                raise ValueError("Buddy request already exists")
            # Re-activate a removed buddy by setting status back to pending
            existing_buddy.requester_id = requester_id
            existing_buddy.accepter_id = accepter_id
            existing_buddy.status = "pending"
            existing_buddy.removed_at = None
            existing_buddy.removed_by = None
            existing_buddy.buddy_streak = 0
            existing_buddy.created_at = datetime.now().replace(tzinfo=None)
            buddy = existing_buddy
        else:
            buddy = Buddy(requester_id=requester_id, accepter_id=accepter_id)
            postgres_session.add(buddy)
        await postgres_session.commit()
        await postgres_session.refresh(buddy)

        # Notify the accepter about the incoming buddy request
        from lib.core.container import container
        from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
        resolver = container.resolve(PatientNameResolver)
        requester_name = await resolver.resolve_first_name(str(requester_id))
        await send_gamification_notification(
            str(accepter_id),
            title="New buddy request",
            body=f"{requester_name} wants to be your buddy.",
            data={"event_type": "buddy_request_received", "requester_id": str(requester_id)},
        )

        return buddy

    @with_postgres_session
    async def send_request_by_code(
        self,
        requester_id: UUID,
        buddy_code: str,
        *,
        postgres_session: AsyncSession,
    ) -> Buddy:
        """Look up a patient by buddy code and send a buddy request."""
        result = await postgres_session.execute(
            select(PlayerProfile.patient_id).where(
                PlayerProfile.buddy_code == buddy_code.upper(),
            )
        )
        target_id = result.scalar()
        if not target_id:
            raise ValueError("Invalid buddy code")

        return await self.send_request(requester_id, target_id)

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

        # Notify the requester that their request was accepted
        from lib.core.container import container
        from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
        resolver = container.resolve(PatientNameResolver)
        accepter_name = await resolver.resolve_first_name(str(accepter_id))
        await send_gamification_notification(
            str(buddy.requester_id),
            title="Buddy request accepted",
            body=f"{accepter_name} accepted your buddy request!",
            data={"event_type": "buddy_request_accepted", "buddy_id": str(buddy.buddy_id)},
        )

        return buddy

    @with_postgres_session
    async def reject_request(
        self,
        buddy_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Reject a pending buddy request. Only the accepter can reject."""
        result = await postgres_session.execute(
            select(Buddy).where(
                Buddy.buddy_id == buddy_id,
                Buddy.accepter_id == patient_id,
                Buddy.status == "pending",
            )
        )
        buddy = result.scalars().first()
        if not buddy:
            raise ValueError("Pending request not found")

        buddy.status = "removed"
        buddy.removed_at = datetime.now().replace(tzinfo=None)
        buddy.removed_by = patient_id
        await postgres_session.commit()

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

        # Batch-load names and timezones for all buddy partners
        other_ids = [
            b.accepter_id if b.requester_id == patient_id else b.requester_id
            for b in buddies
        ]
        names_map: dict = {}
        tz_map: dict = {}
        if other_ids:
            names_result = await postgres_session.execute(
                select(Patient.patient_id, Patient.first_name, Patient.locale).where(
                    Patient.patient_id.in_(other_ids)
                )
            )
            for r in names_result.all():
                names_map[r.patient_id] = r.first_name
                tz_map[r.patient_id] = r.locale

        # Batch-load today's task progress for all buddies
        task_progress: dict = {}  # other_id -> (completed, total)
        if other_ids:
            for oid in other_ids:
                today = local_today(tz_map.get(oid))
                task_result = await postgres_session.execute(
                    select(DailyTask).where(
                        DailyTask.patient_id == oid,
                        DailyTask.task_date == today,
                    )
                )
                tasks = task_result.scalars().all()
                completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED.value)
                task_progress[oid] = (completed, len(tasks))

        responses = []
        for b in buddies:
            other_id = (
                b.accepter_id if b.requester_id == patient_id else b.requester_id
            )
            direction = None
            if b.status == "pending":
                direction = "outgoing" if b.requester_id == patient_id else "incoming"
            completed, total = task_progress.get(other_id, (0, 0))
            responses.append(
                BuddyResponse(
                    buddy_id=str(b.buddy_id),
                    buddy_patient_id=str(other_id),
                    buddy_name=names_map.get(other_id),
                    status=b.status,
                    direction=direction,
                    buddy_streak=b.buddy_streak,
                    buddy_streak_longest=b.buddy_streak_longest,
                    tasks_completed_today=completed,
                    tasks_total_today=total,
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

        # Recent achievements (last 5 slugs) — joined to avoid N+1
        from lib.models.gamification import Achievement

        ach_result = await postgres_session.execute(
            select(PatientAchievement, Achievement)
            .join(Achievement)
            .where(PatientAchievement.patient_id == other_id)
            .order_by(PatientAchievement.earned_at.desc())
            .limit(5)
        )
        recent_slugs = [
            row.Achievement.slug
            for row in ach_result.all()
            if row.Achievement.slug
        ]

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

    @with_postgres_session
    async def get_buddy_detail(
        self,
        buddy_code: str,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ):
        """Rich buddy details by buddy_code (the buddy's personal share code)."""
        from lib.schemas.gamification import BuddyDetailResponse
        from lib.models.gamification import Achievement

        # Resolve buddy_code → other patient_id
        code_normalized = buddy_code.upper().strip()
        code_result = await postgres_session.execute(
            select(PlayerProfile.patient_id).where(
                PlayerProfile.buddy_code == code_normalized
            )
        )
        other_id = code_result.scalar()
        if not other_id:
            raise ValueError(f"No patient found with buddy code '{code_normalized}'")

        # Don't let patient look up themselves
        if other_id == patient_id:
            raise ValueError("That's your own buddy code")

        # Find the buddy relationship between this patient and the resolved one
        result = await postgres_session.execute(
            select(Buddy).where(
                or_(
                    (Buddy.requester_id == patient_id) & (Buddy.accepter_id == other_id),
                    (Buddy.accepter_id == patient_id) & (Buddy.requester_id == other_id),
                ),
                Buddy.status.in_(["active", "pending"]),
            )
        )
        buddy = result.scalars().first()
        if not buddy:
            raise ValueError("No buddy relationship exists with this patient. Send a buddy request first.")

        direction = None
        if buddy.status == "pending":
            direction = "outgoing" if buddy.requester_id == patient_id else "incoming"

        # Buddy's profile (name, picture, locale)
        patient_result = await postgres_session.execute(
            select(
                Patient.first_name,
                Patient.last_name,
                Patient.profile_picture,
                Patient.locale,
            ).where(Patient.patient_id == other_id)
        )
        patient_row = patient_result.first()

        # Buddy's gamification profile
        profile_result = await postgres_session.execute(
            select(PlayerProfile).where(PlayerProfile.patient_id == other_id)
        )
        profile = profile_result.scalars().first()

        # Today's tasks in buddy's timezone
        today = local_today(patient_row.locale if patient_row else None)
        task_result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == other_id,
                DailyTask.task_date == today,
            )
        )
        tasks = task_result.scalars().all()
        completed = sum(1 for t in tasks if t.status == TaskStatus.COMPLETED.value)

        # Recent achievements (last 5)
        ach_result = await postgres_session.execute(
            select(PatientAchievement, Achievement)
            .join(Achievement)
            .where(PatientAchievement.patient_id == other_id)
            .order_by(PatientAchievement.earned_at.desc())
            .limit(5)
        )
        recent_slugs = [
            row.Achievement.slug
            for row in ach_result.all()
            if row.Achievement.slug
        ]

        return BuddyDetailResponse(
            buddy_id=str(buddy.buddy_id),
            buddy_patient_id=str(other_id),
            first_name=patient_row.first_name if patient_row else None,
            last_name=patient_row.last_name if patient_row else None,
            profile_picture=patient_row.profile_picture if patient_row else None,
            status=buddy.status,
            direction=direction,
            buddy_streak=buddy.buddy_streak,
            buddy_streak_longest=buddy.buddy_streak_longest,
            level=profile.level if profile else 1,
            title=title_for_level(profile.level if profile else 1),
            total_xp=profile.total_xp if profile else 0,
            current_streak=profile.current_streak if profile else 0,
            longest_streak=profile.longest_streak if profile else 0,
            tasks_completed_today=completed,
            tasks_total_today=len(tasks),
            recent_achievements=recent_slugs,
            created_at=buddy.created_at,
            accepted_at=buddy.accepted_at,
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
