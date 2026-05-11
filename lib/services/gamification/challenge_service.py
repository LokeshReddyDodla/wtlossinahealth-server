"""Challenge lifecycle — creation, participation, ranking, completion."""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.services.gamification.queries import active_group_ids
from lib.models.gamification import (
    Challenge,
    ChallengeParticipant,
    DailyTask,
    Group,
    GroupMember,
    PlayerProfile,
)
from lib.models.patient import Patient
from lib.schemas.gamification import (
    ChallengeDetailResponse,
    ChallengeParticipantResponse,
    ChallengeResponse,
    title_for_level,
)
from lib.services.gamification.time_utils import local_today
from lib.services.gamification.xp_service import XPService
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class ChallengeService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        xp_service: XPService,
    ) -> None:
        self.postgres_store = postgres_store
        self.xp_service = xp_service

    @with_postgres_session
    async def create_challenge(
        self,
        title: str,
        challenge_type: str,
        scope: str,
        metric_type: str,
        target_value: float,
        duration_days: int,
        xp_reward: int,
        created_by_id: UUID,
        created_by_type: str,
        *,
        description: Optional[str] = None,
        bonus_xp_winner: int = 0,
        facility_id: Optional[UUID] = None,
        is_opt_in: bool = False,
        patient_ids: Optional[List[UUID]] = None,
        group_ids: Optional[List[UUID]] = None,
        postgres_session: AsyncSession,
    ) -> Challenge:
        start_date = local_today(None)
        end_date = start_date + timedelta(days=max(duration_days - 1, 0))

        challenge = Challenge(
            title=title,
            description=description,
            challenge_type=challenge_type,
            scope=scope,
            metric_type=metric_type,
            target_value=target_value,
            duration_days=duration_days,
            start_date=start_date,
            end_date=end_date,
            xp_reward=xp_reward,
            bonus_xp_winner=bonus_xp_winner,
            created_by_id=created_by_id,
            created_by_type=created_by_type,
            facility_id=facility_id,
            is_opt_in=is_opt_in,
        )
        postgres_session.add(challenge)
        await postgres_session.flush()

        enrolled_patient_ids: set[UUID] = set()

        # Auto-enroll the creator if they're a patient
        if created_by_type == "patient":
            postgres_session.add(
                ChallengeParticipant(
                    challenge_id=challenge.challenge_id,
                    participant_type="patient",
                    participant_id=created_by_id,
                )
            )
            enrolled_patient_ids.add(created_by_id)

        # Auto-enroll specified patients
        if patient_ids and not is_opt_in:
            for pid in patient_ids:
                if pid in enrolled_patient_ids:
                    continue
                participant = ChallengeParticipant(
                    challenge_id=challenge.challenge_id,
                    participant_type="patient",
                    participant_id=pid,
                )
                postgres_session.add(participant)
                enrolled_patient_ids.add(pid)

        # Auto-enroll groups (only for non-opt-in challenges)
        if group_ids and not is_opt_in:
            for gid in group_ids:
                participant = ChallengeParticipant(
                    challenge_id=challenge.challenge_id,
                    participant_type="group",
                    participant_id=gid,
                )
                postgres_session.add(participant)

        if (
            scope == "facility"
            and facility_id
            and not is_opt_in
            and not patient_ids
        ):
            facility_patients = await postgres_session.execute(
                select(Patient.patient_id).where(
                    Patient.health_facility_id == facility_id
                )
            )
            for pid in facility_patients.scalars().all():
                if pid in enrolled_patient_ids:
                    continue
                postgres_session.add(
                    ChallengeParticipant(
                        challenge_id=challenge.challenge_id,
                        participant_type="patient",
                        participant_id=pid,
                    )
                )
                enrolled_patient_ids.add(pid)

        await postgres_session.commit()
        await postgres_session.refresh(challenge)

        # Notify auto-enrolled patients about the new challenge
        from lib.services.gamification.notifications import send_gamification_notification
        notify_ids = (enrolled_patient_ids - {created_by_id}) if created_by_type == "patient" else enrolled_patient_ids
        for pid in notify_ids:
            await send_gamification_notification(
                str(pid),
                title="New challenge",
                body=f"You've been enrolled in {title}.",
                data={"event_type": "challenge_enrolled", "challenge_id": str(challenge.challenge_id)},
            )

        return challenge

    @with_postgres_session
    async def join_challenge(
        self,
        challenge_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> ChallengeParticipant:
        challenge = await self._get_challenge(challenge_id, postgres_session)
        if not challenge or not challenge.is_active:
            raise ValueError("Challenge not found or inactive")
        if not challenge.is_opt_in:
            raise ValueError("This challenge does not allow opt-in")
        if await self._patient_today(patient_id, postgres_session) > challenge.end_date:
            raise ValueError("Challenge has ended")

        existing = await postgres_session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.participant_id == patient_id,
            )
        )
        if existing.scalars().first():
            raise ValueError("Already participating")

        participant = ChallengeParticipant(
            challenge_id=challenge_id,
            participant_type="patient",
            participant_id=patient_id,
        )
        postgres_session.add(participant)
        await postgres_session.commit()
        await postgres_session.refresh(participant)
        return participant

    @with_postgres_session
    async def update_participant_progress(
        self,
        patient_id: UUID,
        metric_type: str,
        increment: float,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Increment progress on active challenge participants relevant to a patient."""
        today = await self._patient_today(patient_id, postgres_session)
        now = datetime.now().replace(tzinfo=None)

        patient_rows = await postgres_session.execute(
            select(ChallengeParticipant, Challenge)
            .join(Challenge)
            .where(
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.status == "active",
                Challenge.is_active == True,
                Challenge.metric_type == metric_type,
                Challenge.start_date <= today,
                Challenge.end_date >= today,
            )
        )

        group_ids = await active_group_ids(patient_id, postgres_session)
        group_rows = []
        if group_ids:
            # Exclude challenges the patient individually withdrew from
            withdrawn_ids = (
                select(ChallengeParticipant.challenge_id).where(
                    ChallengeParticipant.participant_id == patient_id,
                    ChallengeParticipant.participant_type == "patient",
                    ChallengeParticipant.status == "withdrawn",
                )
            ).scalar_subquery()

            group_rows_result = await postgres_session.execute(
                select(ChallengeParticipant, Challenge)
                .join(Challenge)
                .where(
                    ChallengeParticipant.participant_id.in_(group_ids),
                    ChallengeParticipant.participant_type == "group",
                    ChallengeParticipant.status == "active",
                    Challenge.is_active == True,
                    Challenge.metric_type == metric_type,
                    Challenge.start_date <= today,
                    Challenge.end_date >= today,
                    Challenge.challenge_id.notin_(withdrawn_ids),
                )
            )
            group_rows = group_rows_result.all()

        rows = list(patient_rows.all()) + list(group_rows)
        for row in rows:
            participant = row.ChallengeParticipant
            challenge = row.Challenge
            participant.current_value += increment
            if participant.current_value >= challenge.target_value and participant.status != "completed":
                participant.status = "completed"
                participant.completed_at = now

        if rows:
            await postgres_session.commit()

    @with_postgres_session
    async def withdraw_from_challenge(
        self,
        challenge_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        result = await postgres_session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.status == "active",
            )
        )
        participant = result.scalars().first()
        if not participant:
            raise ValueError("Not participating in this challenge")

        participant.status = "withdrawn"

        # Expire today's challenge task so it disappears from the task list
        from lib.services.gamification.time_utils import local_today, get_patient_timezone
        tz_name = await get_patient_timezone(patient_id, postgres_session)
        today = local_today(tz_name)
        task_type = f"CHALLENGE_TASK_{challenge_id.hex}"
        task_result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.patient_id == patient_id,
                DailyTask.task_date == today,
                DailyTask.task_type == task_type,
                DailyTask.status == "pending",
            )
        )
        task = task_result.scalars().first()
        if task:
            task.status = "expired"

        await postgres_session.commit()

    @with_postgres_session
    async def get_available_challenges(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[ChallengeResponse]:
        today = await self._patient_today(patient_id, postgres_session)
        patient_groups = await postgres_session.execute(
            select(GroupMember.group_id).where(
                GroupMember.patient_id == patient_id,
                GroupMember.is_active == True,
            )
        )
        group_ids = list(patient_groups.scalars().all())

        result = await postgres_session.execute(
            select(Challenge).where(
                Challenge.is_active == True,
                Challenge.end_date >= today,
                Challenge.is_opt_in == True,
            )
        )
        challenges = result.scalars().all()
        responses = []
        for c in challenges:
            existing_participant = await postgres_session.execute(
                select(ChallengeParticipant.id).where(
                    ChallengeParticipant.challenge_id == c.challenge_id,
                    or_(
                        (
                            (ChallengeParticipant.participant_type == "patient")
                            & (ChallengeParticipant.participant_id == patient_id)
                        ),
                        (
                            (ChallengeParticipant.participant_type == "group")
                            & (ChallengeParticipant.participant_id.in_(group_ids))
                        ),
                    ),
                )
            )
            if existing_participant.scalar():
                continue
            count = await self._participant_count(
                c.challenge_id, postgres_session
            )
            responses.append(self._to_response(c, count))
        return responses

    @with_postgres_session
    async def get_active_challenges(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[ChallengeResponse]:
        today = await self._patient_today(patient_id, postgres_session)
        group_ids = await active_group_ids(patient_id, postgres_session)

        patient_result = await postgres_session.execute(
            select(Challenge)
            .join(ChallengeParticipant)
            .where(
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.status == "active",
                Challenge.is_active == True,
                Challenge.start_date <= today,
                Challenge.end_date >= today,
            )
        )
        challenges = list(patient_result.scalars().all())

        if group_ids:
            # Exclude challenges the patient individually withdrew from
            withdrawn_ids = (
                select(ChallengeParticipant.challenge_id).where(
                    ChallengeParticipant.participant_id == patient_id,
                    ChallengeParticipant.participant_type == "patient",
                    ChallengeParticipant.status == "withdrawn",
                )
            ).scalar_subquery()

            group_result = await postgres_session.execute(
                select(Challenge)
                .join(ChallengeParticipant)
                .where(
                    ChallengeParticipant.participant_id.in_(group_ids),
                    ChallengeParticipant.participant_type == "group",
                    ChallengeParticipant.status == "active",
                    Challenge.is_active == True,
                    Challenge.start_date <= today,
                    Challenge.end_date >= today,
                    Challenge.challenge_id.notin_(withdrawn_ids),
                )
            )
            challenges.extend(group_result.scalars().all())

        deduped: "OrderedDict[UUID, Challenge]" = OrderedDict()
        for challenge in challenges:
            deduped[challenge.challenge_id] = challenge

        responses = []
        for c in deduped.values():
            count = await self._participant_count(
                c.challenge_id, postgres_session
            )
            responses.append(self._to_response(c, count))
        return responses

    @with_postgres_session
    async def get_challenge_detail(
        self,
        challenge_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> ChallengeDetailResponse:
        challenge = await self._get_challenge(challenge_id, postgres_session)
        if not challenge:
            raise ValueError("Challenge not found")

        count = await self._participant_count(
            challenge_id, postgres_session
        )

        # My progress
        my_result = await postgres_session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.participant_type == "patient",
            )
        )
        my_participant = my_result.scalars().first()

        if not my_participant:
            group_ids_result = await postgres_session.execute(
                select(GroupMember.group_id).where(
                    GroupMember.patient_id == patient_id,
                    GroupMember.is_active == True,
                )
            )
            group_ids = list(group_ids_result.scalars().all())
            if group_ids:
                group_participant_result = await postgres_session.execute(
                    select(ChallengeParticipant)
                    .where(
                        ChallengeParticipant.challenge_id == challenge_id,
                        ChallengeParticipant.participant_type == "group",
                        ChallengeParticipant.participant_id.in_(group_ids),
                    )
                    .order_by(ChallengeParticipant.current_value.desc())
                )
                my_participant = group_participant_result.scalars().first()

        # Leaderboard (top 20)
        lb_result = await postgres_session.execute(
            select(ChallengeParticipant)
            .where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.status.in_(["active", "completed"]),
            )
            .order_by(ChallengeParticipant.current_value.desc())
            .limit(20)
        )
        participants = lb_result.scalars().all()

        leaderboard = []
        for idx, p in enumerate(participants, 1):
            name = await self._participant_display_name(p, postgres_session)

            leaderboard.append(
                ChallengeParticipantResponse(
                    participant_type=p.participant_type,
                    participant_id=str(p.participant_id),
                    participant_name=name,
                    current_value=p.current_value,
                    status=p.status,
                    rank=idx,
                    xp_earned=p.xp_earned,
                )
            )

        my_progress = None
        if my_participant:
            my_progress = ChallengeParticipantResponse(
                participant_type=my_participant.participant_type,
                participant_id=str(my_participant.participant_id),
                current_value=my_participant.current_value,
                status=my_participant.status,
                rank=my_participant.rank,
                xp_earned=my_participant.xp_earned,
            )

        return ChallengeDetailResponse(
            challenge=self._to_response(challenge, count),
            my_progress=my_progress,
            leaderboard=leaderboard,
        )

    @with_postgres_session
    async def finalize_challenge(
        self,
        challenge_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """End a challenge: compute rankings, grant XP."""
        challenge = await self._get_challenge(challenge_id, postgres_session)
        if not challenge:
            return

        result = await postgres_session.execute(
            select(ChallengeParticipant)
            .where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.status.in_(["active", "completed"]),
            )
            .order_by(ChallengeParticipant.current_value.desc())
        )
        participants = result.scalars().all()

        now = datetime.now().replace(tzinfo=None)
        for idx, p in enumerate(participants, 1):
            p.rank = idx
            if p.current_value >= challenge.target_value:
                p.status = "completed"
                p.completed_at = now

        challenge.is_active = False

        # Expire today's challenge tasks for all participants
        from lib.services.gamification.time_utils import local_today
        today = local_today(None)
        task_type = f"CHALLENGE_TASK_{challenge_id.hex}"
        task_result = await postgres_session.execute(
            select(DailyTask).where(
                DailyTask.task_type == task_type,
                DailyTask.task_date == today,
                DailyTask.status == "pending",
            )
        )
        for task in task_result.scalars().all():
            task.status = "expired"

        await postgres_session.commit()

        # Grant XP
        for p in participants:
            xp = self._participant_reward_xp(challenge, p)
            if xp <= 0:
                continue

            patient_ids: list[UUID]
            if p.participant_type == "patient":
                patient_ids = [p.participant_id]
            elif p.participant_type == "group":
                patient_ids = await self._active_group_member_ids(
                    p.participant_id, postgres_session
                )
            else:
                patient_ids = []

            for pid in patient_ids:
                await self.xp_service.grant_xp(
                    patient_id=pid,
                    amount=xp,
                    source_type="challenge",
                    source_id=challenge.challenge_id,
                    description=f"Challenge: {challenge.title} (rank #{p.rank})",
                    respect_cap=False,
                )
            p.xp_earned = xp

        await postgres_session.commit()

        # Post feed events for winners and completers
        try:
            from lib.core.container import container
            from lib.services.gamification.feed_service import FeedService
            feed = container.resolve(FeedService)
            for p in participants:
                actor_ids = (
                    [p.participant_id]
                    if p.participant_type == "patient"
                    else await self._active_group_member_ids(
                        p.participant_id, postgres_session
                    )
                )
                for actor_id in actor_ids:
                    if p.rank == 1 and p.status == "completed":
                        await feed.post_event(
                            actor_id=actor_id,
                            event_type="challenge_won",
                            event_data={"title": challenge.title, "rank": 1},
                            visibility="group",
                            group_id=(
                                p.participant_id
                                if p.participant_type == "group"
                                else None
                            ),
                        )
                    elif p.status == "completed":
                        await feed.post_event(
                            actor_id=actor_id,
                            event_type="challenge_completed",
                            event_data={"title": challenge.title, "rank": p.rank},
                            visibility="group",
                            group_id=(
                                p.participant_id
                                if p.participant_type == "group"
                                else None
                            ),
                        )
                    elif p.participant_type == "patient":
                        # Non-completers: notify but don't post feed event
                        from lib.services.gamification.notifications import send_gamification_notification
                        await send_gamification_notification(
                            str(actor_id),
                            title="Challenge ended",
                            body=f"The {challenge.title} challenge has ended. Better luck next time!",
                            data={"event_type": "challenge_ended", "challenge_id": str(challenge.challenge_id)},
                        )
        except Exception:
            logger.warning("Failed to post feed events for challenge %s", challenge_id, exc_info=True)

    @with_postgres_session
    async def get_finalizable_challenge_ids(
        self,
        *,
        postgres_session: AsyncSession,
    ) -> List[UUID]:
        result = await postgres_session.execute(
            select(Challenge).where(Challenge.is_active == True)
        )
        challenges = result.scalars().all()
        finalizable: List[UUID] = []

        for challenge in challenges:
            participant_ids = await self._challenge_patient_ids(
                challenge.challenge_id,
                postgres_session,
            )
            if not participant_ids:
                if local_today(None) > challenge.end_date:
                    finalizable.append(challenge.challenge_id)
                continue

            tz_result = await postgres_session.execute(
                select(Patient.locale).where(Patient.patient_id.in_(participant_ids))
            )
            if all(local_today(tz_name) > challenge.end_date for tz_name in tz_result.scalars().all()):
                finalizable.append(challenge.challenge_id)

        return finalizable

    @with_postgres_session
    async def get_challenge_leaderboard(
        self,
        challenge_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[ChallengeParticipantResponse]:
        detail = await self.get_challenge_detail(
            challenge_id, patient_id, postgres_session=postgres_session
        )
        return detail.leaderboard

    @with_postgres_session
    async def update_challenge(
        self,
        challenge_id: UUID,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        target_value: Optional[float] = None,
        xp_reward: Optional[int] = None,
        bonus_xp_winner: Optional[int] = None,
        postgres_session: AsyncSession,
    ) -> ChallengeResponse:
        """Edit metadata on a challenge. Schedule/scope/type are immutable once created."""
        challenge = await self._get_challenge(challenge_id, postgres_session)
        if not challenge:
            raise ValueError("Challenge not found")
        if not challenge.is_active:
            raise ValueError("Cannot edit an inactive challenge")

        if title is not None:
            challenge.title = title
        if description is not None:
            challenge.description = description
        if target_value is not None:
            challenge.target_value = target_value
        if xp_reward is not None:
            challenge.xp_reward = xp_reward
        if bonus_xp_winner is not None:
            challenge.bonus_xp_winner = bonus_xp_winner

        await postgres_session.commit()
        await postgres_session.refresh(challenge)
        count = await self._participant_count(challenge_id, postgres_session)
        return self._to_response(challenge, count)

    @with_postgres_session
    async def cancel_challenge(
        self,
        challenge_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Soft-cancel a challenge: mark inactive and withdraw all participants."""
        challenge = await self._get_challenge(challenge_id, postgres_session)
        if not challenge:
            raise ValueError("Challenge not found")
        if not challenge.is_active:
            return

        challenge.is_active = False

        participants_result = await postgres_session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.status == "active",
            )
        )
        for participant in participants_result.scalars().all():
            participant.status = "withdrawn"

        await postgres_session.commit()

    async def _get_challenge(
        self, challenge_id: UUID, session: AsyncSession
    ) -> Optional[Challenge]:
        result = await session.execute(
            select(Challenge).where(Challenge.challenge_id == challenge_id)
        )
        return result.scalars().first()

    async def _participant_count(
        self, challenge_id: UUID, session: AsyncSession
    ) -> int:
        result = await session.execute(
            select(func.count(ChallengeParticipant.id)).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.status.in_(["active", "completed"]),
            )
        )
        return result.scalar() or 0

    async def _active_group_member_ids(
        self,
        group_id: UUID,
        session: AsyncSession,
    ) -> List[UUID]:
        result = await session.execute(
            select(GroupMember.patient_id).where(
                GroupMember.group_id == group_id,
                GroupMember.is_active == True,
            )
        )
        return list(result.scalars().all())

    async def _challenge_patient_ids(
        self,
        challenge_id: UUID,
        session: AsyncSession,
    ) -> List[UUID]:
        result = await session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.status.in_(["active", "completed"]),
            )
        )
        participant_ids: set[UUID] = set()
        for participant in result.scalars().all():
            if participant.participant_type == "patient":
                participant_ids.add(participant.participant_id)
            elif participant.participant_type == "group":
                participant_ids.update(
                    await self._active_group_member_ids(
                        participant.participant_id,
                        session,
                    )
                )
        return list(participant_ids)

    async def _patient_today(
        self,
        patient_id: UUID,
        session: AsyncSession,
    ) -> date:
        result = await session.execute(
            select(Patient.locale).where(Patient.patient_id == patient_id)
        )
        return local_today(result.scalar())

    async def _participant_display_name(
        self,
        participant: ChallengeParticipant,
        session: AsyncSession,
    ) -> Optional[str]:
        if participant.participant_type == "patient":
            result = await session.execute(
                select(Patient.first_name).where(
                    Patient.patient_id == participant.participant_id
                )
            )
            return result.scalar()

        if participant.participant_type == "group":
            result = await session.execute(
                select(Group.name).where(Group.group_id == participant.participant_id)
            )
            return result.scalar()

        return None

    def _participant_reward_xp(
        self,
        challenge: Challenge,
        participant: ChallengeParticipant,
    ) -> int:
        xp = 0

        if participant.participant_type == "group":
            if challenge.scope == "group_competitive":
                xp = challenge.xp_reward
            elif challenge.scope in ("group_cooperative", "facility"):
                xp = challenge.xp_reward if participant.status == "completed" else 0
            else:
                xp = challenge.xp_reward if participant.status == "completed" else 0
        else:
            xp = challenge.xp_reward if participant.status == "completed" else 0

        if (
            participant.rank == 1
            and challenge.bonus_xp_winner > 0
            and (
                participant.status == "completed"
                or challenge.scope == "group_competitive"
            )
        ):
            xp += challenge.bonus_xp_winner
        return xp

    @staticmethod
    def _to_response(
        c: Challenge, participant_count: int
    ) -> ChallengeResponse:
        return ChallengeResponse(
            challenge_id=str(c.challenge_id),
            title=c.title,
            description=c.description,
            challenge_type=c.challenge_type,
            scope=c.scope,
            metric_type=c.metric_type,
            target_value=c.target_value,
            duration_days=c.duration_days,
            start_date=c.start_date,
            end_date=c.end_date,
            xp_reward=c.xp_reward,
            bonus_xp_winner=c.bonus_xp_winner,
            created_by_id=str(c.created_by_id),
            created_by_type=c.created_by_type,
            is_opt_in=c.is_opt_in,
            is_active=c.is_active,
            participant_count=participant_count,
            created_at=c.created_at,
        )
