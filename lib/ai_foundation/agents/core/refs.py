"""
Ref resolution — anchor a conversation to specific entities by typed reference.

The frontend passes ``refs=[{type, id}, ...]`` in the request. Each ref is
resolved to a :class:`ResolvedRef` carrying enough context (title, summary,
payload, occurred_at) for the agent to ground its reasoning in those entities.

Single source of truth: Qdrant ``patient_data`` collection for patient
entities. The one exception is ``insight``, which lives in MongoDB
(``ai_proactive_insights``) because it's an agent output, not patient data.

Tenant safety: every Qdrant resolver verifies ``payload.patient_id`` matches
the requesting patient before returning. Refs cannot leak across patients.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pydantic import BaseModel, Field
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from lib.core.qdrant_store import QDRANT_COLLECTION, QdrantStore

if TYPE_CHECKING:
    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker

logger = logging.getLogger(__name__)


class RefType(str, Enum):
    """Entity types that can be referenced from the API."""

    MEAL = "meal"
    SMBG = "smbg"
    VITAL = "vital"
    WORKOUT = "workout"
    DIET_PLAN = "diet_plan"
    FITNESS_PLAN = "fitness_plan"
    MOOD = "mood"
    SYMPTOM = "symptom"
    DOCUMENT = "document"
    CGM_REPORT = "cgm_report"
    INSIGHT = "insight"
    BODY_COMPOSITION = "body_composition"


class Ref(BaseModel):
    """A typed pointer to an entity the user is talking about."""

    type: RefType
    id: str = Field(min_length=1, max_length=128)


@dataclass
class ResolvedRef:
    """A ref hydrated with enough context for the LLM to reason about it."""

    type: RefType
    id: str
    title: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: str | None = None


# Maps RefType → Qdrant data_type for direct md5(entity_id) retrieval.
_DIRECT_DATA_TYPES: dict[RefType, str] = {
    RefType.MEAL: "meal",
    RefType.SMBG: "smbg",
    RefType.VITAL: "vital",
    RefType.WORKOUT: "patient_workout",
    RefType.DIET_PLAN: "diet_plan",
    RefType.FITNESS_PLAN: "fitness_plan",
    RefType.MOOD: "mood_entry",
    RefType.SYMPTOM: "symptom_entry",
    RefType.DOCUMENT: "patient_document",
    RefType.BODY_COMPOSITION: "body_composition",
}


def _md5(value: str) -> str:
    """Mirror of :meth:`PointIdGenerator.generate_simple` — md5 hex of entity id."""
    return hashlib.md5(value.encode()).hexdigest()


def _format_occurred_at(value: Any, tz: str | None) -> str | None:
    """Localize an epoch-ms or datetime to ``tz``, formatted for prompts.

    Mirrors the format used by the previous pinned-insight loader so the
    LLM sees consistent timestamps regardless of source.
    """
    if value is None:
        return None
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError:
        ZoneInfo = None  # type: ignore[assignment]
        ZoneInfoNotFoundError = Exception  # type: ignore[assignment, misc]

    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        elif isinstance(value, datetime):
            dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        else:
            return str(value)

        # Never surface raw UTC to a patient-facing string — the default
        # patient timezone is the fallback when the caller has none.
        if ZoneInfo is not None:
            from lib.ai_foundation.config import settings as _ai_settings

            for tz_name in (tz, _ai_settings.DEFAULT_PATIENT_TIMEZONE):
                if not tz_name:
                    continue
                try:
                    local = dt.astimezone(ZoneInfo(tz_name))
                    return local.strftime("%b %d, %Y at %I:%M %p %Z")
                except ZoneInfoNotFoundError:
                    continue
        return dt.strftime("%b %d, %Y at %I:%M %p UTC")
    except Exception as exc:
        logger.debug("Failed to format occurred_at %r: %s", value, exc)
        return None


async def _retrieve_simple(
    *, ref_id: str, patient_id: str, expected_data_type: str
) -> dict[str, Any] | None:
    """Direct retrieve by md5(ref_id) with tenant + data_type guards.

    Returns the payload dict, or ``None`` if the point doesn't exist, belongs
    to a different patient, or has the wrong data_type. Never raises across
    the guards — callers don't need to distinguish those cases.
    """
    point_id = _md5(ref_id)
    try:
        store = QdrantStore()
        async with store.get_client() as client:
            points = await client.retrieve(
                collection_name=QDRANT_COLLECTION,
                ids=[point_id],
                with_payload=True,
            )
    except Exception as exc:
        logger.warning("Qdrant retrieve failed for ref %s: %s", ref_id, exc)
        return None

    if not points:
        return None
    payload = points[0].payload or {}
    if payload.get("patient_id") != patient_id:
        return None
    if payload.get("data_type") != expected_data_type:
        return None
    return dict(payload)


def _direct_title(ref_type: RefType, payload: dict[str, Any]) -> str:
    """Build a short human label from payload fields per ref type."""
    if ref_type is RefType.MEAL:
        return payload.get("meal_name") or payload.get("meal_type") or "Meal"
    if ref_type is RefType.SMBG:
        return "Blood glucose reading"
    if ref_type is RefType.VITAL:
        return "Vital reading"
    if ref_type is RefType.WORKOUT:
        return payload.get("workout_name") or payload.get("activity_type") or "Workout"
    if ref_type is RefType.DIET_PLAN:
        return payload.get("plan_name") or payload.get("title") or "Diet plan"
    if ref_type is RefType.FITNESS_PLAN:
        return payload.get("plan_name") or payload.get("title") or "Fitness plan"
    if ref_type is RefType.MOOD:
        emoji = payload.get("mood_emoji") or ""
        level = payload.get("mood_level")
        if emoji and level is not None:
            return f"Mood {emoji} (level {level})"
        return "Mood entry"
    if ref_type is RefType.SYMPTOM:
        return payload.get("symptom_name") or payload.get("title") or "Symptom"
    if ref_type is RefType.DOCUMENT:
        return payload.get("document_name") or payload.get("title") or "Document"
    if ref_type is RefType.BODY_COMPOSITION:
        return "Body composition scan"
    return ref_type.value


async def _resolve_direct(
    ref_type: RefType, *, patient_id: str, ref_id: str, tz: str | None
) -> ResolvedRef | None:
    """Resolver for entities stored as a single Qdrant point keyed by md5(id)."""
    expected = _DIRECT_DATA_TYPES[ref_type]
    payload = await _retrieve_simple(
        ref_id=ref_id, patient_id=patient_id, expected_data_type=expected
    )
    if not payload:
        return None
    return ResolvedRef(
        type=ref_type,
        id=ref_id,
        title=_direct_title(ref_type, payload),
        summary=payload.get("text_repr", "") or "",
        payload=payload,
        occurred_at=_format_occurred_at(payload.get("start_time"), tz),
    )


# CGM report — multiple Qdrant points share one report_id. Concatenate their
# text_repr values in deterministic order so the prompt sees the full picture.
_CGM_DATA_TYPE_ORDER = (
    "cgm_summary",
    "cgm_range",
    "time_period_stats",
    "agp_point",
    "hyper_event",
    "hypo_event",
    "cgm_semantic_window",
)


async def _resolve_cgm_report(
    *, patient_id: str, ref_id: str, tz: str | None
) -> ResolvedRef | None:
    """Resolve a CGM report by ``report_id`` via payload-filter scroll."""
    flt = Filter(
        must=[
            FieldCondition(key="patient_id", match=MatchValue(value=patient_id)),
            FieldCondition(key="report_id", match=MatchValue(value=ref_id)),
        ]
    )
    try:
        store = QdrantStore()
        async with store.get_client() as client:
            points, _ = await client.scroll(
                collection_name=QDRANT_COLLECTION,
                scroll_filter=flt,
                limit=32,
                with_payload=True,
                with_vectors=False,
            )
    except Exception as exc:
        logger.warning("Qdrant scroll failed for cgm_report %s: %s", ref_id, exc)
        return None

    if not points:
        return None

    def _order_key(p: Any) -> tuple[int, int]:
        dt = (p.payload or {}).get("data_type", "")
        try:
            primary = _CGM_DATA_TYPE_ORDER.index(dt)
        except ValueError:
            primary = len(_CGM_DATA_TYPE_ORDER)
        secondary = (p.payload or {}).get("start_time") or 0
        return (primary, int(secondary))

    sorted_points = sorted(points, key=_order_key)
    parts: list[str] = []
    start_time: int | None = None
    end_time: int | None = None
    aggregated_payload: dict[str, Any] = {"sections": []}
    for p in sorted_points:
        payload = dict(p.payload or {})
        text = payload.get("text_repr") or ""
        if text:
            parts.append(text)
        if start_time is None or (payload.get("start_time") and payload["start_time"] < start_time):
            start_time = payload.get("start_time")
        if end_time is None or (payload.get("end_time") and payload["end_time"] > end_time):
            end_time = payload.get("end_time")
        aggregated_payload["sections"].append(
            {"data_type": payload.get("data_type"), "payload": payload}
        )

    start_str = _format_occurred_at(start_time, tz) or ""
    end_str = _format_occurred_at(end_time, tz) or ""
    if start_str and end_str:
        title = f"CGM report: {start_str} – {end_str}"
    else:
        title = "CGM report"

    return ResolvedRef(
        type=RefType.CGM_REPORT,
        id=ref_id,
        title=title,
        summary="\n\n".join(parts),
        payload=aggregated_payload,
        occurred_at=start_str or None,
    )


async def _resolve_insight(
    *,
    patient_id: str,
    ref_id: str,
    tz: str | None,
    insight_tracker: InsightTracker | None,
) -> ResolvedRef | None:
    """Insight resolver — the only non-Qdrant resolver (insights live in MongoDB)."""
    if insight_tracker is None:
        return None
    try:
        doc = await insight_tracker.get_by_insight_id(ref_id)
    except Exception as exc:
        logger.warning("Insight lookup failed for %s: %s", ref_id, exc)
        return None
    if not doc:
        return None
    if doc.get("patient_id") != patient_id:
        return None  # tenant guard
    return ResolvedRef(
        type=RefType.INSIGHT,
        id=ref_id,
        title=doc.get("title", "") or "Health insight",
        summary=doc.get("message", "") or "",
        payload=doc,
        occurred_at=_format_occurred_at(doc.get("created_at"), tz),
    )


ResolverFn = Callable[..., Awaitable["ResolvedRef | None"]]


async def resolve_refs(
    *,
    patient_id: str,
    refs: list[Ref] | None,
    tz: str | None = None,
    insight_tracker: InsightTracker | None = None,
) -> list[ResolvedRef]:
    """Resolve all refs in parallel; preserve input order, drop unresolved."""
    if not refs:
        return []

    async def _one(r: Ref) -> ResolvedRef | None:
        if r.type is RefType.CGM_REPORT:
            return await _resolve_cgm_report(patient_id=patient_id, ref_id=r.id, tz=tz)
        if r.type is RefType.INSIGHT:
            return await _resolve_insight(
                patient_id=patient_id, ref_id=r.id, tz=tz, insight_tracker=insight_tracker
            )
        if r.type in _DIRECT_DATA_TYPES:
            return await _resolve_direct(
                r.type, patient_id=patient_id, ref_id=r.id, tz=tz
            )
        return None

    results = await asyncio.gather(*[_one(r) for r in refs])
    return [r for r in results if r is not None]
