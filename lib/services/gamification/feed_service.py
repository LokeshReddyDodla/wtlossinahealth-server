"""Activity feed and cheers management."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    ActivityFeedEvent,
    Buddy,
    Cheer,
    GroupMember,
)
from lib.models.patient import Patient
from lib.schemas.gamification import FeedEventResponse
from lib.services.gamification.xp_service import XPService
from lib.utils.postgres_session_decorator import with_postgres_session

CHEERS_PER_DAY_LIMIT = 3
CHEER_XP = 5
FEED_EXPIRY_DAYS = 30


class FeedService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        xp_service: XPService,
    ) -> None:
        self.postgres_store = postgres_store
        self.xp_service = xp_service

    @with_postgres_session
    async def post_event(
        self,
        actor_id: UUID,
        event_type: str,
        event_data: Dict[str, Any],
        visibility: str,
        *,
        group_id: Optional[UUID] = None,
        postgres_session: AsyncSession,
    ) -> ActivityFeedEvent:
        expires_at = datetime.now().replace(tzinfo=None) + timedelta(
            days=FEED_EXPIRY_DAYS
        )
        event = ActivityFeedEvent(
            actor_id=actor_id,
            event_type=event_type,
            event_data=event_data,
            visibility=visibility,
            group_id=group_id,
            expires_at=expires_at,
        )
        postgres_session.add(event)
        await postgres_session.commit()
        await postgres_session.refresh(event)
        return event

    @with_postgres_session
    async def get_buddy_feed(
        self,
        patient_id: UUID,
        *,
        limit: int = 30,
        postgres_session: AsyncSession,
    ) -> List[FeedEventResponse]:
        from sqlalchemy import or_

        # Get active buddy IDs
        buddy_result = await postgres_session.execute(
            select(Buddy).where(
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
                Buddy.status == "active",
            )
        )
        buddies = buddy_result.scalars().all()
        buddy_ids = set()
        for b in buddies:
            buddy_ids.add(
                b.accepter_id if b.requester_id == patient_id else b.requester_id
            )

        if not buddy_ids:
            return []

        result = await postgres_session.execute(
            select(ActivityFeedEvent)
            .where(
                ActivityFeedEvent.actor_id.in_(buddy_ids),
                ActivityFeedEvent.visibility.in_(["buddy", "group", "public"]),
            )
            .order_by(ActivityFeedEvent.created_at.desc())
            .limit(limit)
        )
        events = result.scalars().all()
        return await self._enrich_events(events, patient_id, postgres_session)

    @with_postgres_session
    async def get_group_feed(
        self,
        group_id: UUID,
        patient_id: UUID,
        *,
        limit: int = 30,
        postgres_session: AsyncSession,
    ) -> List[FeedEventResponse]:
        # Verify membership
        member_check = await postgres_session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id,
                GroupMember.patient_id == patient_id,
                GroupMember.is_active == True,
            )
        )
        if not member_check.scalars().first():
            raise ValueError("Not a member of this group")

        # Get all member IDs
        members_result = await postgres_session.execute(
            select(GroupMember.patient_id).where(
                GroupMember.group_id == group_id,
                GroupMember.is_active == True,
            )
        )
        member_ids = list(members_result.scalars().all())

        result = await postgres_session.execute(
            select(ActivityFeedEvent)
            .where(
                ActivityFeedEvent.actor_id.in_(member_ids),
                ActivityFeedEvent.visibility.in_(["group", "public"]),
            )
            .order_by(ActivityFeedEvent.created_at.desc())
            .limit(limit)
        )
        events = result.scalars().all()
        return await self._enrich_events(events, patient_id, postgres_session)

    @with_postgres_session
    async def send_cheer(
        self,
        sender_id: UUID,
        feed_event_id: UUID,
        reaction: str,
        *,
        postgres_session: AsyncSession,
    ) -> Cheer:
        # Check daily limit
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        count_result = await postgres_session.execute(
            select(func.count(Cheer.cheer_id)).where(
                Cheer.sender_id == sender_id,
                Cheer.created_at >= today_start,
            )
        )
        if (count_result.scalar() or 0) >= CHEERS_PER_DAY_LIMIT:
            raise ValueError(
                f"Maximum {CHEERS_PER_DAY_LIMIT} cheers per day"
            )

        # Get the feed event to find recipient
        event_result = await postgres_session.execute(
            select(ActivityFeedEvent).where(
                ActivityFeedEvent.feed_id == feed_event_id
            )
        )
        event = event_result.scalars().first()
        if not event:
            raise ValueError("Feed event not found")

        if event.actor_id == sender_id:
            raise ValueError("Cannot cheer your own event")

        # Check for duplicate
        existing = await postgres_session.execute(
            select(Cheer).where(
                Cheer.sender_id == sender_id,
                Cheer.feed_event_id == feed_event_id,
            )
        )
        if existing.scalars().first():
            raise ValueError("Already cheered this event")

        cheer = Cheer(
            sender_id=sender_id,
            recipient_id=event.actor_id,
            feed_event_id=feed_event_id,
            reaction=reaction,
        )
        postgres_session.add(cheer)
        await postgres_session.commit()

        # Grant XP to cheerer
        await self.xp_service.grant_xp(
            patient_id=sender_id,
            amount=CHEER_XP,
            source_type="cheer",
            source_id=cheer.cheer_id,
            description=f"Cheered a friend",
        )

        return cheer

    @with_postgres_session
    async def cleanup_expired(
        self, *, postgres_session: AsyncSession
    ) -> int:
        now = datetime.now().replace(tzinfo=None)
        result = await postgres_session.execute(
            delete(ActivityFeedEvent).where(
                ActivityFeedEvent.expires_at < now
            )
        )
        await postgres_session.commit()
        return result.rowcount or 0

    async def _enrich_events(
        self,
        events: List[ActivityFeedEvent],
        viewer_id: UUID,
        session: AsyncSession,
    ) -> List[FeedEventResponse]:
        responses = []
        for event in events:
            # Get actor name
            name_result = await session.execute(
                select(Patient.first_name).where(
                    Patient.patient_id == event.actor_id
                )
            )
            name = name_result.scalar()

            # Get cheer count
            cheer_count_result = await session.execute(
                select(func.count(Cheer.cheer_id)).where(
                    Cheer.feed_event_id == event.feed_id
                )
            )
            cheer_count = cheer_count_result.scalar() or 0

            # Get my cheer on this event
            my_cheer_result = await session.execute(
                select(Cheer.reaction).where(
                    Cheer.feed_event_id == event.feed_id,
                    Cheer.sender_id == viewer_id,
                )
            )
            my_cheer = my_cheer_result.scalar()

            responses.append(
                FeedEventResponse(
                    feed_id=str(event.feed_id),
                    actor_id=str(event.actor_id),
                    actor_name=name,
                    event_type=event.event_type,
                    event_data=event.event_data or {},
                    cheer_count=cheer_count,
                    my_cheer=my_cheer,
                    created_at=event.created_at,
                )
            )
        return responses
