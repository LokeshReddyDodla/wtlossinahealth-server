"""
Patient Name Resolver — lightweight lookup for patient names from Postgres.

Used by the Health Query Agent to replace UUIDs with human-readable names
in multi-patient responses so the LLM can say "Ahmed had 3 hypos" instead
of "7538e5a0-da8b-4745-95d5-ac1ceefd2c76 had 3 hypos".
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lib.core.postgres_store import PostgresStore

logger = logging.getLogger(__name__)


class PatientNameResolver:
    """Resolves patient UUIDs to display names.

    Caches results in-memory for the lifetime of the resolver instance
    (typically one per request or singleton).

    Args:
        postgres_store: The ``PostgresStore`` from ``lib/core``.
    """

    def __init__(self, postgres_store: PostgresStore) -> None:
        self._store = postgres_store
        self._cache: dict[str, str] = {}

    async def resolve_names(self, patient_ids: list[str]) -> dict[str, str]:
        """Resolve a list of patient UUIDs to display names.

        Returns a dict mapping patient_id → display name.
        Unknown IDs are returned as shortened UUIDs (first 8 chars).
        """
        # Check cache first
        uncached = [pid for pid in patient_ids if pid not in self._cache]

        if uncached:
            await self._fetch_names(uncached)

        return {
            pid: self._cache.get(pid, pid[:8])
            for pid in patient_ids
        }

    async def resolve_name(self, patient_id: str) -> str:
        """Resolve a single patient UUID to a display name."""
        names = await self.resolve_names([patient_id])
        return names.get(patient_id, patient_id[:8])

    async def _fetch_names(self, patient_ids: list[str]) -> None:
        """Fetch names from Postgres and populate cache."""
        try:
            from sqlalchemy import select, text
            from lib.models.patient import Patient

            async with self._store.session_local() as session:
                # Lightweight query — only first_name and last_name
                stmt = (
                    select(
                        Patient.patient_id,
                        Patient.first_name,
                        Patient.last_name,
                    )
                    .where(Patient.patient_id.in_(patient_ids))
                )
                result = await session.execute(stmt)
                rows = result.all()

                for row in rows:
                    pid = str(row.patient_id)
                    first = row.first_name or ""
                    last = row.last_name or ""
                    name = f"{first} {last}".strip()
                    self._cache[pid] = name if name else f"Patient ({pid[:8]})"

            # Fill missing IDs (not in Postgres at all)
            for pid in patient_ids:
                if pid not in self._cache:
                    self._cache[pid] = f"Patient ({pid[:8]})"

        except Exception as exc:
            logger.warning("Failed to resolve patient names: %s", exc)
            for pid in patient_ids:
                if pid not in self._cache:
                    self._cache[pid] = f"Patient ({pid[:8]})"
