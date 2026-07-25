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
from lib.core.types import DEFAULT_AI_LANGUAGE

if TYPE_CHECKING:
    from lib.core.postgres_store import PostgresStore

logger = logging.getLogger(__name__)


def fallback_name(pid: str) -> str:
    """Default display name when patient lookup fails."""
    return f"Patient ({pid[:8]})"


class PatientProfile(BaseModel):
    """Minimal patient info for thread display."""

    patient_id: str
    name: str
    profile_picture: str | None = None
    timezone: str | None = None
    preferred_ai_language: str | None = None


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
        return {pid: self._name_cache.get(pid, fallback_name(pid)) for pid in patient_ids}

    async def resolve_name(self, patient_id: str) -> str:
        names = await self.resolve_names([patient_id])
        return names.get(patient_id, fallback_name(patient_id))

    async def resolve_first_name(self, patient_id: str) -> str:
        """Resolve a patient UUID to first name only (for notifications)."""
        stale = self._collect_stale([patient_id])
        if stale:
            await self._fetch(stale)
        profile = self._profile_cache.get(patient_id)
        if profile and profile.name:
            return profile.name.split()[0]
        return fallback_name(patient_id)

    # -- Timezones (for proactive monitor) ---------------------------------

    async def resolve_timezones(self, patient_ids: list[str]) -> dict[str, str]:
        """Resolve patient UUIDs to IANA timezone strings."""
        stale = self._collect_stale(patient_ids)
        if stale:
            await self._fetch(stale)
        return {
            pid: self._profile_cache[pid].timezone or settings.DEFAULT_PATIENT_TIMEZONE
            for pid in patient_ids
            if pid in self._profile_cache
        }

    # -- AI response language ----------------------------------------------

    async def resolve_languages(self, patient_ids: list[str]) -> dict[str, str]:
        """Resolve patient UUIDs to preferred AI language codes ("en" default)."""
        stale = self._collect_stale(patient_ids)
        if stale:
            await self._fetch(stale)
        return {
            pid: self._profile_cache[pid].preferred_ai_language or DEFAULT_AI_LANGUAGE
            for pid in patient_ids
            if pid in self._profile_cache
        }

    async def resolve_language(self, patient_id: str) -> str:
        langs = await self.resolve_languages([patient_id])
        return langs.get(patient_id, DEFAULT_AI_LANGUAGE)

    # -- Profiles (for thread list UI) -------------------------------------

    async def resolve_profiles(self, patient_ids: list[str]) -> list[PatientProfile]:
        """Resolve patient UUIDs to name + profile_picture."""
        stale = self._collect_stale(patient_ids)
        if stale:
            await self._fetch(stale)
        return [
            self._profile_cache.get(pid, PatientProfile(
                patient_id=pid, name=fallback_name(pid),
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
                        Patient.timezone,
                        Patient.preferred_ai_language,
                    )
                    .where(Patient.patient_id.in_(patient_ids))
                )
                result = await session.execute(stmt)
                rows = result.all()

                for row in rows:
                    pid = str(row.patient_id)
                    first = row.first_name or ""
                    last = row.last_name or ""
                    name = f"{first} {last}".strip() or fallback_name(pid)

                    self._name_cache[pid] = name
                    self._profile_cache[pid] = PatientProfile(
                        patient_id=pid,
                        name=name,
                        profile_picture=row.profile_picture,
                        timezone=row.timezone,
                        preferred_ai_language=row.preferred_ai_language,
                    )
                    self._timestamps[pid] = fetched_at

            for pid in patient_ids:
                if pid not in self._name_cache:
                    self._name_cache[pid] = fallback_name(pid)
                    self._profile_cache[pid] = PatientProfile(
                        patient_id=pid, name=fallback_name(pid),
                    )
                # Cache misses too so unknown IDs do not trigger repeated DB hits.
                self._timestamps[pid] = fetched_at

            self._evict_if_needed()

        except Exception as exc:
            logger.warning("Failed to resolve patients: %s", exc)
            for pid in patient_ids:
                if pid not in self._name_cache:
                    self._name_cache[pid] = fallback_name(pid)
                    self._profile_cache[pid] = PatientProfile(
                        patient_id=pid, name=fallback_name(pid),
                    )
                self._timestamps[pid] = fetched_at
