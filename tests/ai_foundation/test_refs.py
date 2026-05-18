"""Tests for the typed-ref resolution system."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.ai_foundation.agents.core import refs as refs_mod
from lib.ai_foundation.agents.core.refs import (
    Ref,
    RefType,
    ResolvedRef,
    _md5,
    resolve_refs,
)


# ---------------------------------------------------------------------------
# Helpers — fake Qdrant client
# ---------------------------------------------------------------------------


class _FakeQdrantClient:
    """In-memory stand-in for AsyncQdrantClient covering retrieve + scroll."""

    def __init__(self, points: list[SimpleNamespace]) -> None:
        self._points = points

    async def retrieve(self, *, collection_name, ids, with_payload=True):
        return [p for p in self._points if p.id in ids]

    async def scroll(
        self,
        *,
        collection_name,
        scroll_filter,
        limit,
        with_payload=True,
        with_vectors=False,
    ):
        # Apply filter: every condition in `must` is patient_id or report_id match
        must = scroll_filter.must or []
        wanted = {c.key: c.match.value for c in must}
        matched = []
        for p in self._points:
            if all((p.payload or {}).get(k) == v for k, v in wanted.items()):
                matched.append(p)
        return matched[:limit], None


@pytest.fixture
def fake_store(monkeypatch):
    """Patches QdrantStore so refs.py uses our in-memory client."""
    points: list[SimpleNamespace] = []

    @asynccontextmanager
    async def _client_ctx(self):
        yield _FakeQdrantClient(points)

    monkeypatch.setattr(refs_mod.QdrantStore, "get_client", _client_ctx)
    return points


def _point(*, ref_id: str, patient_id: str, data_type: str, **payload) -> SimpleNamespace:
    full = {
        "patient_id": patient_id,
        "data_type": data_type,
        "text_repr": payload.pop("text_repr", f"[{data_type}] details"),
        "start_time": payload.pop("start_time", 1714867200000),  # 2024-05-05 00:00 UTC
        "end_time": payload.pop("end_time", 1714867200000),
        **payload,
    }
    return SimpleNamespace(id=_md5(ref_id), payload=full)


# ---------------------------------------------------------------------------
# Direct-retrieve resolvers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_meal(fake_store):
    fake_store.append(
        _point(
            ref_id="meal-1",
            patient_id="p1",
            data_type="meal",
            meal_name="Avocado toast",
            text_repr="Patient ate avocado toast at 9am",
        )
    )
    out = await resolve_refs(
        patient_id="p1", refs=[Ref(type=RefType.MEAL, id="meal-1")], tz=None
    )
    assert len(out) == 1
    assert out[0].type is RefType.MEAL
    assert out[0].title == "Avocado toast"
    assert "avocado toast" in out[0].summary.lower()
    assert out[0].occurred_at and "2024" in out[0].occurred_at


@pytest.mark.parametrize(
    "ref_type, data_type, id_field, name_field, expected_title",
    [
        (RefType.WORKOUT, "patient_workout", "wo-1", "workout_name", "Morning run"),
        (RefType.DIET_PLAN, "diet_plan", "plan-1", "plan_name", "Low-carb plan"),
        (RefType.SYMPTOM, "symptom_entry", "s-1", "symptom_name", "Headache"),
        (RefType.DOCUMENT, "patient_document", "d-1", "document_name", "Lab report PDF"),
    ],
)
@pytest.mark.asyncio
async def test_resolve_simple_titles(
    fake_store, ref_type, data_type, id_field, name_field, expected_title
):
    fake_store.append(
        _point(
            ref_id=id_field,
            patient_id="p1",
            data_type=data_type,
            **{name_field: expected_title},
        )
    )
    out = await resolve_refs(
        patient_id="p1", refs=[Ref(type=ref_type, id=id_field)], tz=None
    )
    assert len(out) == 1 and out[0].title == expected_title


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_guard(fake_store):
    fake_store.append(_point(ref_id="meal-x", patient_id="patientA", data_type="meal", meal_name="Steak"))
    out = await resolve_refs(
        patient_id="patientB", refs=[Ref(type=RefType.MEAL, id="meal-x")], tz=None
    )
    assert out == []  # cross-patient leak prevented


@pytest.mark.asyncio
async def test_data_type_guard(fake_store):
    # A workout point exists at md5("wo-1"), but caller asks for it as a meal.
    fake_store.append(_point(ref_id="wo-1", patient_id="p1", data_type="patient_workout", workout_name="Run"))
    out = await resolve_refs(
        patient_id="p1", refs=[Ref(type=RefType.MEAL, id="wo-1")], tz=None
    )
    assert out == []


@pytest.mark.asyncio
async def test_missing_point(fake_store):
    out = await resolve_refs(
        patient_id="p1", refs=[Ref(type=RefType.MEAL, id="nope")], tz=None
    )
    assert out == []


# ---------------------------------------------------------------------------
# CGM report — multi-point concat via scroll
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_cgm_report_concatenates_sections(fake_store):
    # Two points share the same report_id, different data_types.
    common = {"patient_id": "p1", "report_id": "rep-1", "start_time": 1714867200000, "end_time": 1714953600000}
    fake_store.extend(
        [
            SimpleNamespace(
                id="x1",
                payload={**common, "data_type": "cgm_summary", "text_repr": "TIR 65%"},
            ),
            SimpleNamespace(
                id="x2",
                payload={**common, "data_type": "hyper_event", "text_repr": "Hyper at 10am"},
            ),
        ]
    )
    out = await resolve_refs(
        patient_id="p1", refs=[Ref(type=RefType.CGM_REPORT, id="rep-1")], tz=None
    )
    assert len(out) == 1
    summary = out[0].summary
    assert "TIR 65%" in summary and "Hyper at 10am" in summary
    # cgm_summary should come before hyper_event (deterministic order)
    assert summary.index("TIR 65%") < summary.index("Hyper at 10am")
    assert out[0].title.startswith("CGM report")
    assert len(out[0].payload["sections"]) == 2


@pytest.mark.asyncio
async def test_cgm_report_other_patient_filtered_out(fake_store):
    fake_store.append(
        SimpleNamespace(
            id="x1",
            payload={
                "patient_id": "patientA",
                "data_type": "cgm_summary",
                "report_id": "rep-shared",
                "text_repr": "leak",
            },
        )
    )
    out = await resolve_refs(
        patient_id="patientB", refs=[Ref(type=RefType.CGM_REPORT, id="rep-shared")], tz=None
    )
    assert out == []


# ---------------------------------------------------------------------------
# Insight resolver — MongoDB path via injected tracker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_insight(fake_store):
    tracker = MagicMock()
    tracker.get_by_insight_id = AsyncMock(
        return_value={
            "insight_id": "ins-1",
            "patient_id": "p1",
            "title": "Glucose trending high",
            "message": "TIR dropped 15% this week",
            "category": "glucose",
            "severity": "attention",
            "created_at": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        }
    )
    out = await resolve_refs(
        patient_id="p1",
        refs=[Ref(type=RefType.INSIGHT, id="ins-1")],
        tz="Asia/Kolkata",
        insight_tracker=tracker,
    )
    assert len(out) == 1
    assert out[0].title == "Glucose trending high"
    assert "TIR dropped" in out[0].summary
    assert out[0].occurred_at and "2026" in out[0].occurred_at


@pytest.mark.asyncio
async def test_insight_tenant_guard(fake_store):
    tracker = MagicMock()
    tracker.get_by_insight_id = AsyncMock(
        return_value={"insight_id": "ins-x", "patient_id": "patientA", "title": "t", "message": "m"}
    )
    out = await resolve_refs(
        patient_id="patientB",
        refs=[Ref(type=RefType.INSIGHT, id="ins-x")],
        insight_tracker=tracker,
    )
    assert out == []


@pytest.mark.asyncio
async def test_insight_without_tracker_returns_empty(fake_store):
    out = await resolve_refs(
        patient_id="p1",
        refs=[Ref(type=RefType.INSIGHT, id="ins-1")],
        insight_tracker=None,
    )
    assert out == []


# ---------------------------------------------------------------------------
# Mixed input — order preserved, unresolved dropped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_refs_preserves_order_drops_misses(fake_store):
    fake_store.append(_point(ref_id="m-ok", patient_id="p1", data_type="meal", meal_name="Lunch"))
    fake_store.append(_point(ref_id="w-ok", patient_id="p1", data_type="patient_workout", workout_name="Yoga"))
    refs = [
        Ref(type=RefType.MEAL, id="m-ok"),
        Ref(type=RefType.MEAL, id="missing"),
        Ref(type=RefType.WORKOUT, id="w-ok"),
    ]
    out = await resolve_refs(patient_id="p1", refs=refs, tz=None)
    assert [r.title for r in out] == ["Lunch", "Yoga"]


@pytest.mark.asyncio
async def test_resolve_refs_empty_input():
    assert await resolve_refs(patient_id="p1", refs=None) == []
    assert await resolve_refs(patient_id="p1", refs=[]) == []
