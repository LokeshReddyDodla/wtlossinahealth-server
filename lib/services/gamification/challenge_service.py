"""Challenge lifecycle — creation, participation, ranking, completion."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    Challenge,
    ChallengeParticipant,
    PlayerProfile,
)
from lib.models.patient import Patient
from lib.schemas.gamification import (
    ChallengeDetailResponse,
    ChallengeParticipantResponse,
    ChallengeResponse,
    title_for_level,
)
from lib.services.gamification.xp_service import XPService
from lib.utils.postgres_session_decorator import with_postgres_session


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
        start_date = date.today()
        end_date = start_date + timedelta(days=duration_days)

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

        # Auto-enroll specified patients
        if patient_ids and not is_opt_in:
            for pid in patient_ids:
                participant = ChallengeParticipant(
                    challenge_id=challenge.challenge_id,
                    participant_type="patient",
                    participant_id=pid,
                )
                postgres_session.add(participant)

        # Auto-enroll groups
        if group_ids:
            for gid in group_ids:
                participant = ChallengeParticipant(
                    challenge_id=challenge.challenge_id,
                    participant_type="group",
                    participant_id=gid,
                )
                postgres_session.add(participant)

        await postgres_session.commit()
        await postgres_session.refresh(challenge)
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
        if date.today() > challenge.end_date:
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
        """Increment progress on all active challenges matching this metric type."""
        today = date.today()
        result = await postgres_session.execute(
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
        rows = result.all()
        for row in rows:
            participant = row.ChallengeParticipant
            challenge = row.Challenge
            participant.current_value += increment
            if participant.current_value >= challenge.target_value:
                participant.status = "completed"
                participant.completed_at = datetime.now().replace(tzinfo=None)
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
        await postgres_session.commit()

    @with_postgres_session
    async def get_available_challenges(
        self,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> List[ChallengeResponse]:
        today = date.today()
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
        result = await postgres_session.execute(
            select(Challenge)
            .join(ChallengeParticipant)
            .where(
                ChallengeParticipant.participant_id == patient_id,
                ChallengeParticipant.participant_type == "patient",
                ChallengeParticipant.status == "active",
                Challenge.is_active == True,
            )
        )
        challenges = result.scalars().all()
        responses = []
        for c in challenges:
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
            name = None
            if p.participant_type == "patient":
                name_result = await postgres_session.execute(
                    select(Patient.first_name).where(
                        Patient.patient_id == p.participant_id
                    )
                )
                name = name_result.scalar()

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
        await postgres_session.commit()

        # Grant XP
        for p in participants:
            if p.participant_type != "patient":
                continue
            xp = challenge.xp_reward if p.status == "completed" else 0
            if p.rank == 1 and p.status == "completed" and challenge.bonus_xp_winner > 0:
                xp += challenge.bonus_xp_winner
            if xp > 0:
                await self.xp_service.grant_xp(
                    patient_id=p.participant_id,
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
                if p.participant_type != "patient":
                    continue
                if p.rank == 1 and p.status == "completed":
                    await feed.post_event(
                        actor_id=p.participant_id,
                        event_type="challenge_won",
                        event_data={"title": challenge.title, "rank": 1},
                        visibility="group",
                    )
                elif p.status == "completed":
                    await feed.post_event(
                        actor_id=p.participant_id,
                        event_type="challenge_completed",
                        event_data={"title": challenge.title, "rank": p.rank},
                        visibility="group",
                    )
        except Exception:
            pass

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

    def _to_response(
        self, c: Challenge, participant_count: int
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
