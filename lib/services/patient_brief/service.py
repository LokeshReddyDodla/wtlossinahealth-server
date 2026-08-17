"""Provider AI Patient Brief — lazy generation, cached, manual refresh.

The brief is a once-a-day artifact: data streams in fast (CGM every ~5 min),
but the patient's *state* changes slowly, so we regenerate on a slow cadence,
not per data event. Generation happens only for patients a provider actually
opens (or refreshes) — cost scales with usage, not census.

One brief per patient; the generation history lives in Langfuse.
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
_FAIL_COOLDOWN = timedelta(seconds=60)


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
        # Patients with a generation in flight — dedupes concurrent views/polls
        # so a first-ever view being polled doesn't spawn a regen every poll.
        self._generating: set[str] = set()

    async def get(self, patient_id: str) -> dict:
        """Never blocks on the LLM. Returns the cached brief immediately (status
        'ready'); on a first-ever or stale view it kicks generation in the
        background and the caller polls."""
        doc = await self._latest(patient_id)
        if not self._has_brief(doc):
            if patient_id in self._generating:
                return {"status": "generating"}
            if self._in_cooldown(doc):
                return {"status": "error"}
            self._ensure_generating(patient_id)
            return {"status": "generating"}
        if self._age(doc) > _TTL and not self._in_cooldown(doc):
            self._ensure_generating(patient_id)
        return {"status": "ready", **self._view(doc), "refreshing": patient_id in self._generating}

    async def refresh(self, patient_id: str) -> dict:
        """Force a fresh brief (the provider clicked refresh), debounced so a
        rapid re-click is a no-op."""
        doc = await self._latest(patient_id)
        if self._has_brief(doc) and self._age(doc) < _DEBOUNCE:
            return {"status": "ready", **self._view(doc), "refreshing": False}
        self._ensure_generating(patient_id)
        if not self._has_brief(doc):
            return {"status": "generating"}
        return {"status": "ready", **self._view(doc), "refreshing": True}

    # ── internals ────────────────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        """Create the patient_id index that serves every lookup. Idempotent.
        Called once at startup (app.main), like the other Mongo-backed services."""
        await self._col.create_index("patient_id", name="patient_briefs_patient_idx")

    async def _latest(self, patient_id: str) -> dict | None:
        return await self._col.find_one(
            {"patient_id": patient_id}, {"_id": 0}, sort=[("generated_at", -1)]
        )

    def _has_brief(self, doc: dict | None) -> bool:
        return bool(doc and doc.get("generated_at"))

    def _view(self, doc: dict) -> dict:
        return {k: v for k, v in doc.items() if k != "failed_at"}

    def _age(self, doc: dict) -> timedelta:
        gen = _as_utc(doc.get("generated_at")) or datetime.now(timezone.utc)
        return datetime.now(timezone.utc) - gen

    def _in_cooldown(self, doc: dict | None) -> bool:
        failed = _as_utc(doc.get("failed_at")) if doc else None
        return failed is not None and datetime.now(timezone.utc) - failed < _FAIL_COOLDOWN

    async def _regenerate(self, patient_id: str) -> dict:
        result = await self._agent.run_provider_brief(patient_id=patient_id)
        doc = {
            "patient_id": patient_id,
            "assessment": result.assessment,
            "verdict": result.verdict,
            "narrative": result.narrative,
            "generated_at": datetime.now(timezone.utc),
        }
        # One brief per patient — replace the current one in a single write.
        await self._col.replace_one({"patient_id": patient_id}, doc, upsert=True)
        return doc

    def _ensure_generating(self, patient_id: str) -> None:
        if patient_id in self._generating:
            return
        self._generating.add(patient_id)
        task = asyncio.create_task(self._safe_regen(patient_id))
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _safe_regen(self, patient_id: str) -> None:
        try:
            await self._regenerate(patient_id)
        except Exception:
            logger.exception("background brief regen failed: %s", patient_id)
            await self._col.update_one(
                {"patient_id": patient_id},
                {"$set": {"failed_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        finally:
            self._generating.discard(patient_id)
