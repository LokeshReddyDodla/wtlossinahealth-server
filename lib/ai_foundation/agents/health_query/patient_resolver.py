"""
Patient Resolver — lightweight lookup for patient names and profile pics.

Used by the Health Query Agent for LLM context (names only) and by the
threads API for UI display (names + profile pics).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.core.postgres_store import PostgresStore

logger = logging.getLogger(__name__)


class PatientProfile(BaseModel):
    """Minimal patient info for thread display."""

    patient_id: str
    name: str
    profile_picture: str | None = None


class PatientNameResolver:
    """Resolves patient UUIDs to names and profile pictures.

    Two methods:
    - resolve_names() → dict[pid, name] — for LLM context (lightweight)
    - resolve_profiles() → list[PatientProfile] — for thread list UI (with pics)
    """

    def __init__(self, postgres_store: PostgresStore) -> None:
        self._store = postgres_store
        self._name_cache: dict[str, str] = {}
        self._profile_cache: dict[str, PatientProfile] = {}

    # -- Names (for LLM context) -------------------------------------------

    async def resolve_names(self, patient_ids: list[str]) -> dict[str, str]:
        """Resolve patient UUIDs to display names."""
        uncached = [pid for pid in patient_ids if pid not in self._name_cache]
        if uncached:
            await self._fetch(uncached)
        return {pid: self._name_cache.get(pid, f"Patient ({pid[:8]})") for pid in patient_ids}

    async def resolve_name(self, patient_id: str) -> str:
        names = await self.resolve_names([patient_id])
        return names.get(patient_id, f"Patient ({patient_id[:8]})")

    # -- Profiles (for thread list UI) -------------------------------------

    async def resolve_profiles(self, patient_ids: list[str]) -> list[PatientProfile]:
        """Resolve patient UUIDs to name + profile_picture."""
        uncached = [pid for pid in patient_ids if pid not in self._profile_cache]
        if uncached:
            await self._fetch(uncached)
        return [
            self._profile_cache.get(pid, PatientProfile(
                patient_id=pid, name=f"Patient ({pid[:8]})",
            ))
            for pid in patient_ids
        ]

    # -- Internal ----------------------------------------------------------

    async def _fetch(self, patient_ids: list[str]) -> None:
        """Fetch name + profile_picture from Postgres."""
        try:
            from sqlalchemy import select
            from lib.models.patient import Patient

            async with self._store.session_local() as session:
                stmt = (
                    select(
                        Patient.patient_id,
                        Patient.first_name,
                        Patient.last_name,
                        Patient.profile_picture,
                    )
                    .where(Patient.patient_id.in_(patient_ids))
                )
                result = await session.execute(stmt)
                rows = result.all()

                for row in rows:
                    pid = str(row.patient_id)
                    first = row.first_name or ""
                    last = row.last_name or ""
                    name = f"{first} {last}".strip() or f"Patient ({pid[:8]})"

                    self._name_cache[pid] = name
                    self._profile_cache[pid] = PatientProfile(
                        patient_id=pid,
                        name=name,
                        profile_picture=row.profile_picture,
                    )

            for pid in patient_ids:
                if pid not in self._name_cache:
                    self._name_cache[pid] = f"Patient ({pid[:8]})"
                    self._profile_cache[pid] = PatientProfile(
                        patient_id=pid, name=f"Patient ({pid[:8]})",
                    )

        except Exception as exc:
            logger.warning("Failed to resolve patients: %s", exc)
            for pid in patient_ids:
                if pid not in self._name_cache:
                    self._name_cache[pid] = f"Patient ({pid[:8]})"
                    self._profile_cache[pid] = PatientProfile(
                        patient_id=pid, name=f"Patient ({pid[:8]})",
                    )
