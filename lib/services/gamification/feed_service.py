"""Activity feed and cheers management."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    ActivityFeedEvent,
    Buddy,
    Cheer,
    GroupMember,
    PlayerProfile,
)
from lib.models.patient import Patient
from lib.schemas.gamification import (
    CHEERS_PER_DAY_LIMIT,
    CHEER_XP_REWARD,
    FEED_EXPIRY_DAYS,
    FeedEventResponse,
)
from lib.services.gamification.notifications import send_gamification_notification
from lib.services.gamification.time_utils import (
    local_today,
    naive_day_bounds_for_local_date,
)
from lib.services.gamification.xp_service import XPService
from lib.utils.postgres_session_decorator import with_postgres_session


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
        return await self._enrich_events(
            events, patient_id, postgres_session, context="buddy"
        )

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
                or_(
                    ActivityFeedEvent.group_id == group_id,
                    ActivityFeedEvent.actor_id.in_(member_ids),
                ),
                ActivityFeedEvent.visibility.in_(["group", "public"]),
            )
            .order_by(ActivityFeedEvent.created_at.desc())
            .limit(limit)
        )
        events = result.scalars().all()
        return await self._enrich_events(
            events, patient_id, postgres_session, context="group"
        )

    @with_postgres_session
    async def send_cheer(
        self,
        sender_id: UUID,
        feed_event_id: UUID,
        reaction: str,
        *,
        postgres_session: AsyncSession,
    ) -> Cheer:
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

        # Verify sender has a relationship with the event actor (buddy or shared group)
        buddy_check = await postgres_session.execute(
            select(Buddy.buddy_id).where(
                Buddy.status == "active",
                or_(
                    (Buddy.requester_id == sender_id) & (Buddy.accepter_id == event.actor_id),
                    (Buddy.requester_id == event.actor_id) & (Buddy.accepter_id == sender_id),
                ),
            )
        )
        is_buddy = buddy_check.scalar() is not None

        if not is_buddy:
            # Check shared group membership
            sender_groups = await postgres_session.execute(
                select(GroupMember.group_id).where(
                    GroupMember.patient_id == sender_id,
                    GroupMember.is_active == True,
                )
            )
            sender_group_ids = set(sender_groups.scalars().all())

            actor_groups = await postgres_session.execute(
                select(GroupMember.group_id).where(
                    GroupMember.patient_id == event.actor_id,
                    GroupMember.is_active == True,
                )
            )
            actor_group_ids = set(actor_groups.scalars().all())

            if not sender_group_ids & actor_group_ids:
                raise ValueError("You can only cheer buddies or group members")

        # Check for existing cheer on this event
        existing_result = await postgres_session.execute(
            select(Cheer).where(
                Cheer.sender_id == sender_id,
                Cheer.feed_event_id == feed_event_id,
            )
        )
        existing = existing_result.scalars().first()

        if existing:
            if existing.reaction == reaction:
                # Same emoji tapped again — undo the cheer
                await postgres_session.delete(existing)
                await postgres_session.commit()
                return None
            # Different emoji — replace
            existing.reaction = reaction
            await postgres_session.commit()
            return existing

        cheer = Cheer(
            sender_id=sender_id,
            recipient_id=event.actor_id,
            feed_event_id=feed_event_id,
            reaction=reaction,
        )
        postgres_session.add(cheer)
        await postgres_session.commit()

        # Grant XP only on first cheer (not on replace/undo)
        await self.xp_service.grant_xp(
            patient_id=sender_id,
            amount=CHEER_XP_REWARD,
            source_type="cheer",
            source_id=cheer.cheer_id,
            description=f"Cheered a friend",
        )

        from lib.core.container import container
        from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
        resolver = container.resolve(PatientNameResolver)
        sender_name = await resolver.resolve_first_name(str(sender_id))
        await send_gamification_notification(
            str(event.actor_id),
            title="You got a cheer",
            body=f"{sender_name} cheered your progress!",
            data={
                "event_type": "buddy_cheer",
                "feed_event_id": str(feed_event_id),
                "sender_id": str(sender_id),
            },
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
        *,
        context: str,
    ) -> List[FeedEventResponse]:
        if not events:
            return []

        actor_ids = list({e.actor_id for e in events})
        feed_ids = [e.feed_id for e in events]

        # Batch: actor names
        names_result = await session.execute(
            select(Patient.patient_id, Patient.first_name).where(
                Patient.patient_id.in_(actor_ids)
            )
        )
        names_map = {r.patient_id: r.first_name for r in names_result.all()}

        # Batch: visibility settings
        vis_result = await session.execute(
            select(
                PlayerProfile.patient_id,
                PlayerProfile.leaderboard_visibility,
            ).where(PlayerProfile.patient_id.in_(actor_ids))
        )
        vis_map = {r.patient_id: r.leaderboard_visibility for r in vis_result.all()}

        # Batch: cheer counts per event
        cheer_counts_result = await session.execute(
            select(
                Cheer.feed_event_id,
                func.count(Cheer.cheer_id).label("cnt"),
            )
            .where(Cheer.feed_event_id.in_(feed_ids))
            .group_by(Cheer.feed_event_id)
        )
        cheer_counts_map = {r.feed_event_id: r.cnt for r in cheer_counts_result.all()}

        # Batch: viewer's cheers
        my_cheers_result = await session.execute(
            select(Cheer.feed_event_id, Cheer.reaction).where(
                Cheer.feed_event_id.in_(feed_ids),
                Cheer.sender_id == viewer_id,
            )
        )
        my_cheers_map = {r.feed_event_id: r.reaction for r in my_cheers_result.all()}

        responses = []
        for event in events:
            name = names_map.get(event.actor_id)
            visibility = vis_map.get(event.actor_id, "group_only")
            visible = self._is_identity_visible(
                viewer_id=viewer_id,
                actor_id=event.actor_id,
                visibility=visibility,
                context=context,
            )

            responses.append(
                FeedEventResponse(
                    feed_id=str(event.feed_id),
                    actor_id=(
                        str(event.actor_id)
                        if visible
                        else f"anonymous:{str(event.feed_id)[:8]}"
                    ),
                    actor_name=name if visible else "Anonymous",
                    event_type=event.event_type,
                    event_data=event.event_data or {},
                    cheer_count=cheer_counts_map.get(event.feed_id, 0),
                    my_cheer=my_cheers_map.get(event.feed_id),
                    created_at=event.created_at,
                )
            )
        return responses

    def _is_identity_visible(
        self,
        *,
        viewer_id: UUID,
        actor_id: UUID,
        visibility: str,
        context: str,
    ) -> bool:
        if viewer_id == actor_id:
            return True
        if context == "buddy":
            return True
        if visibility == "public":
            return True
        if visibility == "group_only":
            return context == "group"
        return False
