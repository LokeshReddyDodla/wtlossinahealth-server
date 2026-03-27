"""
Patient Resolver — lightweight lookup for patient names and profile pics.

Used by the Health Query Agent for LLM context (names only) and by the
threads API for UI display (names + profile pics).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lib.ai_foundation.config import settings

if TYPE_CHECKING:
    from lib.core.postgres_store import PostgresStore

logger = logging.getLogger(__name__)

settings.PATIENT_CACHE_TTL = 300  # 5 minutes


class PatientProfile(BaseModel):
    """Minimal patient info for thread display."""

    patient_id: str
    name: str
    profile_picture: str | None = None
    locale: str | None = None


class PatientNameResolver:
    """Resolves patient UUIDs to names and profile pictures.

    Caches results for 5 minutes to avoid hitting Postgres every request.
    After TTL, re-fetches to pick up name/pic changes.
    """

    def __init__(self, postgres_store: PostgresStore) -> None:
        self._store = postgres_store
        self._name_cache: dict[str, str] = {}
        self._profile_cache: dict[str, PatientProfile] = {}
        self._timestamps: dict[str, float] = {}  # pid → monotonic time

    # -- Names (for LLM context) -------------------------------------------

    async def resolve_names(self, patient_ids: list[str]) -> dict[str, str]:
        """Resolve patient UUIDs to display names."""
        stale = [pid for pid in patient_ids if self._is_stale(pid)]
        if stale:
            await self._fetch(stale)
        return {pid: self._name_cache.get(pid, f"Patient ({pid[:8]})") for pid in patient_ids}

    async def resolve_name(self, patient_id: str) -> str:
        names = await self.resolve_names([patient_id])
        return names.get(patient_id, f"Patient ({patient_id[:8]})")

    # -- Timezones (for proactive monitor) ---------------------------------

    async def resolve_timezones(self, patient_ids: list[str]) -> dict[str, str]:
        """Resolve patient UUIDs to IANA timezone strings (from locale field)."""
        stale = [pid for pid in patient_ids if self._is_stale(pid)]
        if stale:
            await self._fetch(stale)
        return {
            pid: self._profile_cache[pid].locale or "Asia/Kolkata"
            for pid in patient_ids
            if pid in self._profile_cache
        }

    # -- Profiles (for thread list UI) -------------------------------------

    async def resolve_profiles(self, patient_ids: list[str]) -> list[PatientProfile]:
        """Resolve patient UUIDs to name + profile_picture."""
        stale = [pid for pid in patient_ids if self._is_stale(pid)]
        if stale:
            await self._fetch(stale)
        return [
            self._profile_cache.get(pid, PatientProfile(
                patient_id=pid, name=f"Patient ({pid[:8]})",
            ))
            for pid in patient_ids
        ]

    # -- Internal ----------------------------------------------------------

    def _is_stale(self, pid: str) -> bool:
        """Check if cache entry is missing or expired."""
        if pid not in self._name_cache:
            return True
        ts = self._timestamps.get(pid, 0)
        return (time.monotonic() - ts) > settings.PATIENT_CACHE_TTL

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
                        Patient.locale,
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
                        locale=row.locale,
                    )
                    self._timestamps[pid] = time.monotonic()

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
