"""
Patient Resolver — lightweight lookup for patient names and profile pics.

Used by the Health Query Agent for LLM context (names only) and by the
threads API for UI display (names + profile pics).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from pydantic import BaseModel

from lib.ai_foundation.config import settings

if TYPE_CHECKING:
    from lib.core.postgres_store import PostgresStore

logger = logging.getLogger(__name__)


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

    _MAX_CACHE_SIZE = 1000

    def __init__(self, postgres_store: PostgresStore) -> None:
        self._store = postgres_store
        self._name_cache: dict[str, str] = {}
        self._profile_cache: dict[str, PatientProfile] = {}
        self._timestamps: dict[str, float] = {}  # pid → monotonic time

    def _evict_if_needed(self) -> None:
        """Prune oldest 200 entries when cache exceeds max size."""
        if len(self._timestamps) <= self._MAX_CACHE_SIZE:
            return
        oldest = sorted(self._timestamps, key=self._timestamps.get)[:200]  # type: ignore[arg-type]
        for pid in oldest:
            self._name_cache.pop(pid, None)
            self._profile_cache.pop(pid, None)
            self._timestamps.pop(pid, None)

    # -- Names (for LLM context) -------------------------------------------

    async def resolve_names(self, patient_ids: list[str]) -> dict[str, str]:
        """Resolve patient UUIDs to display names."""
        stale = self._collect_stale(patient_ids)
        if stale:
            await self._fetch(stale)
        return {pid: self._name_cache.get(pid, f"Patient ({pid[:8]})") for pid in patient_ids}

    async def resolve_name(self, patient_id: str) -> str:
        names = await self.resolve_names([patient_id])
        return names.get(patient_id, f"Patient ({patient_id[:8]})")

    # -- Timezones (for proactive monitor) ---------------------------------

    async def resolve_timezones(self, patient_ids: list[str]) -> dict[str, str]:
        """Resolve patient UUIDs to IANA timezone strings (from locale field)."""
        stale = self._collect_stale(patient_ids)
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
        stale = self._collect_stale(patient_ids)
        if stale:
            await self._fetch(stale)
        return [
            self._profile_cache.get(pid, PatientProfile(
                patient_id=pid, name=f"Patient ({pid[:8]})",
            ))
            for pid in patient_ids
        ]

    # -- Internal ----------------------------------------------------------

    def _is_stale(self, pid: str, now: float) -> bool:
        """Check if cache entry is missing or expired."""
        if pid not in self._name_cache:
            return True
        ts = self._timestamps.get(pid)
        if ts is None:
            return True
        return (now - ts) > settings.PATIENT_CACHE_TTL

    def _collect_stale(self, patient_ids: list[str]) -> list[str]:
        """Return stale patient IDs, deduplicated while preserving order."""
        now = time.monotonic()
        seen: set[str] = set()
        stale: list[str] = []
        for pid in patient_ids:
            if pid in seen:
                continue
            seen.add(pid)
            if self._is_stale(pid, now):
                stale.append(pid)
        return stale

    async def _fetch(self, patient_ids: list[str]) -> None:
        """Fetch name + profile_picture from Postgres."""
        fetched_at = time.monotonic()
        try:
            from sqlalchemy import select
            from lib.models.patient import Patient

            async with self._store.get_session() as session:
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
                    self._timestamps[pid] = fetched_at

            for pid in patient_ids:
                if pid not in self._name_cache:
                    self._name_cache[pid] = f"Patient ({pid[:8]})"
                    self._profile_cache[pid] = PatientProfile(
                        patient_id=pid, name=f"Patient ({pid[:8]})",
                    )
                # Cache misses too so unknown IDs do not trigger repeated DB hits.
                self._timestamps[pid] = fetched_at

            self._evict_if_needed()

        except Exception as exc:
            logger.warning("Failed to resolve patients: %s", exc)
            for pid in patient_ids:
                if pid not in self._name_cache:
                    self._name_cache[pid] = f"Patient ({pid[:8]})"
                    self._profile_cache[pid] = PatientProfile(
                        patient_id=pid, name=f"Patient ({pid[:8]})",
                    )
                self._timestamps[pid] = fetched_at
