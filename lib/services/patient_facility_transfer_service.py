"""Patient facility transfer — atomically migrates a patient to a new facility.

Cleans up facility-scoped relationships (buddies, groups, challenges) in one
transaction. Health data, achievements, XP, plans, etc. follow the patient.
"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.gamification import (
    Buddy,
    Challenge,
    ChallengeParticipant,
    DailyTask,
    Group,
    GroupMember,
)
from lib.models.health_facility import HealthFacility
from lib.models.patient import Patient
from lib.schemas.gamification import TaskStatus
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)


class PatientFacilityTransferService:
    """Handles atomic patient → new facility migration."""

    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def transfer_patient(
        self,
        patient_id: UUID,
        new_facility_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> dict:
        """Transfer a patient to a new facility.

        Returns a summary of what was cleaned up.
        Notifications sent post-commit (best-effort).
        """
        # ── Validate ─────────────────────────────────────────────────────
        patient_result = await postgres_session.execute(
            select(Patient).where(Patient.patient_id == patient_id)
        )
        patient = patient_result.scalars().first()
        if not patient:
            raise_http_exception(status_code=404, message="Patient not found")

        old_facility_id = patient.health_facility_id
        if old_facility_id == new_facility_id:
            raise_http_exception(
                status_code=400,
                message="Patient is already in this facility",
            )

        facility_result = await postgres_session.execute(
            select(HealthFacility).where(
                HealthFacility.health_facility_id == new_facility_id
            )
        )
        new_facility = facility_result.scalars().first()
        if not new_facility:
            raise_http_exception(status_code=404, message="New facility not found")

        now = datetime.now().replace(tzinfo=None)
        summary = {
            "patient_id": str(patient_id),
            "old_facility_id": str(old_facility_id) if old_facility_id else None,
            "new_facility_id": str(new_facility_id),
            "buddies_removed": 0,
            "groups_left": 0,
            "challenges_withdrawn": 0,
            "removed_buddy_partner_ids": [],
        }

        # ── Step 1: Remove all active/pending buddy relationships ──────
        buddy_result = await postgres_session.execute(
            select(Buddy).where(
                or_(
                    Buddy.requester_id == patient_id,
                    Buddy.accepter_id == patient_id,
                ),
                Buddy.status.in_(["active", "pending"]),
            )
        )
        buddies = list(buddy_result.scalars().all())
        for b in buddies:
            b.status = "removed"
            b.removed_at = now
            b.removed_by = patient_id
            partner_id = (
                b.accepter_id if b.requester_id == patient_id else b.requester_id
            )
            summary["removed_buddy_partner_ids"].append(str(partner_id))
        summary["buddies_removed"] = len(buddies)

        # ── Step 2: Leave facility-scoped groups (only old facility) ───
        if old_facility_id:
            group_member_result = await postgres_session.execute(
                select(GroupMember, Group)
                .join(Group, Group.group_id == GroupMember.group_id)
                .where(
                    GroupMember.patient_id == patient_id,
                    GroupMember.is_active == True,
                    Group.facility_id == old_facility_id,
                )
            )
            rows = list(group_member_result.all())
            for row in rows:
                row.GroupMember.is_active = False
                row.GroupMember.left_at = now
            summary["groups_left"] = len(rows)

            # Expire today's challenge tasks tied to those groups
            if rows:
                left_group_ids = [r.GroupMember.group_id for r in rows]
                # Find group challenges
                group_challenges = await postgres_session.execute(
                    select(ChallengeParticipant.challenge_id).where(
                        ChallengeParticipant.participant_type == "group",
                        ChallengeParticipant.participant_id.in_(left_group_ids),
                    )
                )
                challenge_ids = [r[0] for r in group_challenges.all()]
                if challenge_ids:
                    await postgres_session.execute(
                        update(DailyTask)
                        .where(
                            DailyTask.patient_id == patient_id,
                            DailyTask.task_date == now.date(),
                            DailyTask.status == TaskStatus.PENDING.value,
                            DailyTask.source_type == "challenge",
                            DailyTask.source_id.in_(challenge_ids),
                        )
                        .values(status=TaskStatus.EXPIRED.value)
                    )

        # ── Step 3: Withdraw from facility-scoped challenges (direct) ──
        if old_facility_id:
            challenge_result = await postgres_session.execute(
                select(ChallengeParticipant, Challenge)
                .join(Challenge, Challenge.challenge_id == ChallengeParticipant.challenge_id)
                .where(
                    ChallengeParticipant.participant_id == patient_id,
                    ChallengeParticipant.participant_type == "patient",
                    ChallengeParticipant.status == "active",
                    Challenge.facility_id == old_facility_id,
                )
            )
            challenges = list(challenge_result.all())
            for row in challenges:
                row.ChallengeParticipant.status = "withdrawn"
            summary["challenges_withdrawn"] = len(challenges)

            # Expire today's challenge tasks
            if challenges:
                challenge_ids = [r.ChallengeParticipant.challenge_id for r in challenges]
                await postgres_session.execute(
                    update(DailyTask)
                    .where(
                        DailyTask.patient_id == patient_id,
                        DailyTask.task_date == now.date(),
                        DailyTask.status == TaskStatus.PENDING.value,
                        DailyTask.source_type == "challenge",
                        DailyTask.source_id.in_(challenge_ids),
                    )
                    .values(status=TaskStatus.EXPIRED.value)
                )

        # ── Step 4: Update the patient's facility ──────────────────────
        patient.health_facility_id = new_facility_id

        # Single commit for entire migration
        await postgres_session.commit()

        logger.info(
            "Facility transfer complete: patient=%s, old=%s, new=%s, "
            "buddies_removed=%d, groups_left=%d, challenges_withdrawn=%d",
            patient_id, old_facility_id, new_facility_id,
            summary["buddies_removed"], summary["groups_left"],
            summary["challenges_withdrawn"],
        )

        # ── Step 5: Post-commit notifications (best-effort) ────────────
        await self._send_notifications(
            patient_id=str(patient_id),
            new_facility_name=new_facility.name,
            removed_buddy_ids=summary["removed_buddy_partner_ids"],
        )

        return summary

    async def _send_notifications(
        self,
        patient_id: str,
        new_facility_name: str,
        removed_buddy_ids: list[str],
    ) -> None:
        """Send FCM notifications post-commit."""
        try:
            from lib.services.gamification.notifications import (
                send_gamification_notification,
            )

            # Notify the transferred patient
            await send_gamification_notification(
                patient_id,
                title="Facility transfer complete",
                body=f"You've been transferred to {new_facility_name}.",
                data={"event_type": "facility_transferred"},
            )

            # Notify each removed buddy partner
            for buddy_partner_id in removed_buddy_ids:
                await send_gamification_notification(
                    buddy_partner_id,
                    title="Buddy removed",
                    body="A buddy has been transferred to another facility.",
                    data={"event_type": "buddy_removed_facility_transfer"},
                )
        except Exception:
            logger.exception("Facility transfer notifications failed")
