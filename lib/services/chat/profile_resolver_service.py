"""Batch-resolve compact sender profiles for chat messages.

One service, three PG tables (patients / care_providers / admins) queried
sequentially on a single async session. Returns
dict[user_id, SenderProfileSchema] with synthesized "Unknown User"
entries for any id we can't resolve, so callers never get None.

Sequential — NOT asyncio.gather. Async SQLAlchemy sessions are
single-stream; concurrent execute() calls trip
IllegalStateChangeError. The latency cost of serializing three
simple ``SELECT ... WHERE id IN (...)`` queries is negligible.

This is the shared dependency behind item C (inline sender_profile on
messages) and item F (single-chat fetch). Both flow through the same
batch path so a busy chat with 100 messages from 5 distinct senders is
3 PG queries, not 100.
"""

from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from lib.core.constants import SUPPORT_ASSISTANT_SENDER_ID
from lib.core.postgres_store import PostgresStore
from lib.models.admin import Admin
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.schemas.sender_profile import (
    SUPPORT_ASSISTANT_SENDER_PROFILE,
    SenderProfileRoleLiteral,
    SenderProfileSchema,
    UNKNOWN_SENDER_PROFILE,
)
from lib.utils.postgres_session_decorator import with_postgres_session


SUPPORT_STAFF_ROLE_VALUE = "support_staff"


def _cp_role_split(
    role_value: str | None,
) -> tuple[SenderProfileRoleLiteral, str | None]:
    """Map ``CareProvider.role`` (free string in PG) to the top-level
    sender_profile role enum + an optional subrole.

    - "Support_Staff" (any casing) → ("support_staff", None) — already
      encoded in the top-level enum, no subrole.
    - "Doctor", "Nurse", "Dietitian", ... → ("care_provider", "Doctor").
    - None / "" → ("care_provider", None) — defensive for misconfigured
      CP records.
    """
    if not role_value:
        return "care_provider", None
    if role_value.strip().lower() == SUPPORT_STAFF_ROLE_VALUE:
        return "support_staff", None
    return "care_provider", role_value.strip()


class ProfileResolverService:
    def __init__(self):
        # Required by the @with_postgres_session decorator. PostgresStore is
        # a process-wide singleton via punq elsewhere, but the decorator
        # only reads .postgres_store.get_session(), so plain attribute access
        # is enough here.
        self.postgres_store = PostgresStore()

    @with_postgres_session
    async def resolve(
        self,
        user_ids: Iterable[str],
        *,
        postgres_session: AsyncSession,
    ) -> dict[str, SenderProfileSchema]:
        """Return a profile for every id in ``user_ids``. Missing ids get
        a synthesized ``Unknown User`` profile so callers never need to
        handle None."""
        unique_ids = {str(uid) for uid in user_ids if uid}
        if not unique_ids:
            return {}

        # The support assistant has no PG row; resolve it before the role
        # lookups so it never falls through to "Unknown User".
        resolved_bot: dict[str, SenderProfileSchema] = {}
        if SUPPORT_ASSISTANT_SENDER_ID in unique_ids:
            resolved_bot[SUPPORT_ASSISTANT_SENDER_ID] = SUPPORT_ASSISTANT_SENDER_PROFILE
            unique_ids = unique_ids - {SUPPORT_ASSISTANT_SENDER_ID}
            if not unique_ids:
                return resolved_bot

        # Run the three role lookups sequentially, NOT via asyncio.gather.
        # Async SQLAlchemy sessions are single-stream — concurrent
        # execute() calls trip an IllegalStateChangeError. Each query is
        # a plain SELECT ... WHERE id IN (...); the latency cost of
        # serializing is negligible (~few ms).
        patients = await self._fetch_patients(unique_ids, postgres_session)
        care_providers = await self._fetch_care_providers(
            unique_ids, postgres_session
        )
        admins = await self._fetch_admins(unique_ids, postgres_session)

        resolved: dict[str, SenderProfileSchema] = dict(resolved_bot)
        for uid, patient in patients.items():
            resolved[uid] = SenderProfileSchema(
                first_name=patient.first_name or "",
                last_name=patient.last_name or "",
                profile_picture=patient.profile_picture,
                role="patient",
                subrole=None,
            )
        for uid, cp in care_providers.items():
            role, subrole = _cp_role_split(cp.role)
            resolved[uid] = SenderProfileSchema(
                first_name=cp.first_name or "",
                last_name=cp.last_name or "",
                profile_picture=cp.profile_picture,
                role=role,
                subrole=subrole,
            )
        for uid, admin in admins.items():
            resolved[uid] = SenderProfileSchema(
                first_name="Support",
                last_name="Team",
                profile_picture=None,
                role="admin",
                subrole=None,
            )

        # Synthesize for any leftover ids so callers can rely on
        # non-null sender_profile on every record.
        for uid in unique_ids - set(resolved.keys()):
            resolved[uid] = UNKNOWN_SENDER_PROFILE

        return resolved

    @staticmethod
    async def _fetch_patients(
        ids: set[str], session: AsyncSession
    ) -> dict[str, Patient]:
        if not ids:
            return {}
        result = await session.execute(
            select(Patient).where(Patient.patient_id.in_(ids))
        )
        return {str(p.patient_id): p for p in result.scalars().all()}

    @staticmethod
    async def _fetch_care_providers(
        ids: set[str], session: AsyncSession
    ) -> dict[str, CareProvider]:
        if not ids:
            return {}
        result = await session.execute(
            select(CareProvider).where(
                CareProvider.care_provider_id.in_(ids)
            )
        )
        return {str(cp.care_provider_id): cp for cp in result.scalars().all()}

    @staticmethod
    async def _fetch_admins(
        ids: set[str], session: AsyncSession
    ) -> dict[str, Admin]:
        if not ids:
            return {}
        result = await session.execute(
            select(Admin).where(Admin.id.in_(ids))
        )
        return {str(a.id): a for a in result.scalars().all()}
