"""Provider AI Patient Brief — lazy generation, cached, manual refresh.

The brief is a once-a-day artifact: data streams in fast (CGM every ~5 min),
but the patient's *state* changes slowly, so we regenerate on a slow cadence,
not per data event. Generation happens only for patients a provider actually
opens (or refreshes) — cost scales with usage, not census.

One brief per patient; the generation history lives in Langfuse.
"""

import logging
from datetime import datetime, timedelta, timezone

from lib.ai_foundation.agents.health_query import HealthQueryAgent

logger = logging.getLogger(__name__)

# A brief older than the TTL is refreshed on the next view; a refresh click
# within the debounce window is a no-op (nothing meaningful changed that fast).
_TTL = timedelta(hours=18)
_DEBOUNCE = timedelta(seconds=120)
_FAIL_COOLDOWN = timedelta(seconds=60)
_GENERATION_LEASE = timedelta(minutes=10)
_INTERNAL_FIELDS = {"failed_at", "generation_started_at"}


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class PatientBriefService:
    def __init__(
        self, briefs_collection, health_query_agent: HealthQueryAgent
    ):
        self._col = briefs_collection
        self._agent = health_query_agent

    async def get(self, patient_id: str) -> dict:
        """Never blocks on the LLM. Returns the cached brief immediately (status
        'ready'); on a first-ever or stale view it kicks generation in the
        durable queue and the caller polls."""
        doc = await self._latest(patient_id)
        if not self._has_brief(doc):
            if self._is_generating(doc):
                return {"status": "generating"}
            if self._in_cooldown(doc):
                return {"status": "error"}
            queued = await self._queue_generation(patient_id)
            return {"status": "generating" if queued else "error"}
        refreshing = self._is_generating(doc)
        if (
            self._age(doc) > _TTL
            and not refreshing
            and not self._in_cooldown(doc)
        ):
            refreshing = await self._queue_generation(patient_id)
        return {"status": "ready", **self._view(doc), "refreshing": refreshing}

    async def refresh(self, patient_id: str) -> dict:
        """Force a fresh brief (the provider clicked refresh), debounced so a
        rapid re-click is a no-op."""
        doc = await self._latest(patient_id)
        if self._has_brief(doc) and self._age(doc) < _DEBOUNCE:
            return {"status": "ready", **self._view(doc), "refreshing": False}
        refreshing = self._is_generating(doc) or await self._queue_generation(
            patient_id
        )
        if not self._has_brief(doc):
            return {"status": "generating" if refreshing else "error"}
        return {"status": "ready", **self._view(doc), "refreshing": refreshing}

    # ── internals ────────────────────────────────────────────────────────────

    async def ensure_indexes(self) -> None:
        """Create the patient_id index that serves every lookup. Idempotent.
        Called once at startup (app.main), like the other Mongo-backed services."""
        await self._col.create_index(
            "patient_id", name="patient_briefs_patient_idx"
        )

    async def _latest(self, patient_id: str) -> dict | None:
        return await self._col.find_one(
            {"patient_id": patient_id}, {"_id": 0}, sort=[("generated_at", -1)]
        )

    def _has_brief(self, doc: dict | None) -> bool:
        return bool(doc and doc.get("generated_at"))

    def _view(self, doc: dict) -> dict:
        return {k: v for k, v in doc.items() if k not in _INTERNAL_FIELDS}

    def _age(self, doc: dict) -> timedelta:
        gen = _as_utc(doc.get("generated_at")) or datetime.now(timezone.utc)
        return datetime.now(timezone.utc) - gen

    def _in_cooldown(self, doc: dict | None) -> bool:
        failed = _as_utc(doc.get("failed_at")) if doc else None
        return (
            failed is not None
            and datetime.now(timezone.utc) - failed < _FAIL_COOLDOWN
        )

    def _is_generating(self, doc: dict | None) -> bool:
        started = _as_utc(doc.get("generation_started_at")) if doc else None
        return (
            started is not None
            and datetime.now(timezone.utc) - started < _GENERATION_LEASE
        )

    async def _queue_generation(self, patient_id: str) -> bool:
        now = datetime.now(timezone.utc)
        await self._col.update_one(
            {"patient_id": patient_id},
            {
                "$set": {"generation_started_at": now},
                "$unset": {"failed_at": ""},
            },
            upsert=True,
        )
        try:
            from lib.workers.tasks.patient_brief.tasks import (
                enqueue_patient_brief,
            )

            await enqueue_patient_brief(patient_id, requested_at=now)
            return True
        except Exception:
            logger.exception("patient brief enqueue failed: %s", patient_id)
            await self.mark_failed(patient_id)
            return False

    async def regenerate(self, patient_id: str) -> dict:
        result = await self._agent.run_provider_brief(patient_id=patient_id)
        doc = {
            "patient_id": patient_id,
            "assessment": result.assessment,
            "verdict": result.verdict,
            "narrative": result.narrative,
            "generated_at": datetime.now(timezone.utc),
        }
        # One brief per patient — replace the current one in a single write.
        await self._col.replace_one(
            {"patient_id": patient_id}, doc, upsert=True
        )
        return doc

    async def mark_failed(self, patient_id: str) -> None:
        await self._col.update_one(
            {"patient_id": patient_id},
            {
                "$set": {"failed_at": datetime.now(timezone.utc)},
                "$unset": {"generation_started_at": ""},
            },
            upsert=True,
        )
