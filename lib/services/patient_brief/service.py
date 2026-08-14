"""Provider AI Patient Brief — lazy generation, cached, manual refresh.

The brief is a once-a-day artifact: data streams in fast (CGM every ~5 min),
but the patient's *state* changes slowly, so we regenerate on a slow cadence,
not per data event. Generation happens only for patients a provider actually
opens (or refreshes) — cost scales with usage, not census.

Storage is append-only (audit trail + eval corpus); reads serve the latest.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from lib.ai_foundation.agents.health_query import HealthQueryAgent

logger = logging.getLogger(__name__)

# A brief older than the TTL is refreshed on the next view; a refresh click
# within the debounce window is a no-op (nothing meaningful changed that fast).
_TTL = timedelta(hours=18)
_DEBOUNCE = timedelta(seconds=120)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class PatientBriefService:
    def __init__(self, briefs_collection, health_query_agent: HealthQueryAgent):
        self._col = briefs_collection
        self._agent = health_query_agent
        # Strong refs so background regenerations aren't GC'd mid-flight.
        self._bg_tasks: set[asyncio.Task] = set()

    async def get(self, patient_id: str) -> dict:
        """The current brief. Generates synchronously on first-ever view; if a
        cached brief is stale, returns it immediately and refreshes in the
        background (stale-while-revalidate)."""
        latest = await self._latest(patient_id)
        if latest is None:
            brief = await self._regenerate(patient_id)
            return {**brief, "refreshing": False}
        stale = self._age(latest) > _TTL
        if stale:
            self._spawn_regen(patient_id)
        return {**latest, "refreshing": stale}

    async def refresh(self, patient_id: str) -> dict:
        """Force a fresh brief now (the provider clicked refresh). Debounced so a
        rapid re-click returns the just-generated one instead of regenerating."""
        latest = await self._latest(patient_id)
        if latest is not None and self._age(latest) < _DEBOUNCE:
            return {**latest, "refreshing": False}
        brief = await self._regenerate(patient_id)
        return {**brief, "refreshing": False}

    # ── internals ────────────────────────────────────────────────────────────

    async def _latest(self, patient_id: str) -> dict | None:
        return await self._col.find_one(
            {"patient_id": patient_id}, {"_id": 0}, sort=[("generated_at", -1)]
        )

    def _age(self, doc: dict) -> timedelta:
        gen = _as_utc(doc.get("generated_at")) or datetime.now(timezone.utc)
        return datetime.now(timezone.utc) - gen

    async def _regenerate(self, patient_id: str) -> dict:
        result = await self._agent.run_provider_brief(patient_id=patient_id)
        doc = {
            "patient_id": patient_id,
            "narrative": result.narrative,
            "flags": [f.model_dump() for f in result.flags],
            "generated_at": datetime.now(timezone.utc),
        }
        await self._col.insert_one(dict(doc))  # append-only; copy so _id isn't kept
        return doc

    def _spawn_regen(self, patient_id: str) -> None:
        task = asyncio.create_task(self._safe_regen(patient_id))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _safe_regen(self, patient_id: str) -> None:
        try:
            await self._regenerate(patient_id)
        except Exception:
            logger.exception("background brief regen failed: %s", patient_id)
