"""Tests for MealContextLoader — Qdrant-first parallel loader."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lib.ai_foundation.agents.meal_analysis.context_loader import (
    CGM_EVENT_TYPES,
    DIET_PLAN_DATA_TYPE,
    MEAL_DATA_TYPE,
    MEDICATION_DATA_TYPE,
    PROFILE_DATA_TYPE,
    WORKOUT_DATA_TYPE,
    MealContextLoader,
    _coerce_slot,
    _derive_has_cgm,
    _meal_payload_to_dict,
    _partition_meals_by_date,
    _profile_payload_to_dict,
    _unwrap,
)
from lib.ai_foundation.agents.meal_analysis.contracts import MealSlot
from lib.ai_foundation.retrieval.base import RetrievalResult


def _make_loader(*, qdrant=None, memory=None) -> MealContextLoader:
    if qdrant is None:
        qdrant = MagicMock()
        qdrant.retrieve_filtered = AsyncMock(return_value=[])
    m = memory or MagicMock()
    m.get_patient_facts = AsyncMock(return_value=[])
    return MealContextLoader(
        qdrant_retriever=qdrant,
        memory_store=m,
        postgres_store=MagicMock(),
    )


class TestUnwrap:
    def test_returns_value(self):
        assert _unwrap("ok", "default") == "ok"

    def test_returns_default_on_exception(self):
        assert _unwrap(ValueError("x"), []) == []

    def test_returns_value_even_if_none(self):
        assert _unwrap(None, "default") is None


class TestCoerceSlot:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("breakfast", MealSlot.BREAKFAST),
            ("Breakfast", MealSlot.BREAKFAST),
            ("  LUNCH ", MealSlot.LUNCH),
            ("dinner", MealSlot.DINNER),
            ("snack", MealSlot.SNACK),
        ],
    )
    def test_valid(self, raw, expected):
        assert _coerce_slot(raw) == expected

    @pytest.mark.parametrize("raw", ["", None, "brunch", "tea"])
    def test_invalid(self, raw):
        assert _coerce_slot(raw) is None


class TestMealPayloadToDict:
    def test_maps_qdrant_payload_to_expected_shape(self):
        r = RetrievalResult(
            payload={
                "data_type": "meal",
                "meal_id": "m1",
                "meal_name": "Paratha",
                "meal_type": "breakfast",
                "meal_date": "2026-04-20",
                "meal_time": "08:45:00",
                "nutrition": {"calories": 420, "carbohydrates": 58, "fiber": 4},
                "items": [{"item_name": "paratha", "serving_quantity": 2, "serving_unit": "piece"}],
                "tags": ["high_carb"],
            },
            source="qdrant_filtered",
            data_type="meal",
        )
        out = _meal_payload_to_dict(r)
        assert out["meal_id"] == "m1"
        assert out["name"] == "Paratha"
        assert out["slot"] == "breakfast"
        assert out["consumed_at"] == "2026-04-20T08:45:00"
        assert out["macros"]["calories"] == 420
        assert out["items"][0]["name"] == "paratha"


class TestPartitionMeals:
    def test_groups_today_by_slot(self):
        today = datetime(2026, 4, 20, tzinfo=timezone.utc).date()
        meals = [
            {
                "meal_id": "00000000-0000-0000-0000-000000000001",
                "name": "idli",
                "slot": "breakfast",
                "date": "2026-04-20",
                "consumed_at": "2026-04-20T08:00:00",
            },
            {
                "meal_id": "00000000-0000-0000-0000-000000000002",
                "name": "paratha",
                "slot": "breakfast",
                "date": "2026-04-19",
                "consumed_at": "2026-04-19T08:00:00",
            },
        ]
        recent, by_slot = _partition_meals_by_date(meals, today)
        assert len(recent) == 2  # all meals
        assert MealSlot.BREAKFAST in by_slot
        assert len(by_slot[MealSlot.BREAKFAST]) == 1  # only today's
        assert by_slot[MealSlot.BREAKFAST][0].meal_name == "idli"


class TestProfilePayloadToDict:
    def test_selects_known_keys(self):
        out = _profile_payload_to_dict(
            {
                "age": 42,
                "gender": "female",
                "height": 162,
                "weight": 68,
                "bmi": 25.9,
                "locale": "en_IN",
                "timezone": "Asia/Kolkata",
                "type_of_diabetes": "type_2",
                "years_with_diabetes": 3,
                "extra_field": "ignored",
            }
        )
        assert out["age"] == 42
        assert out["timezone"] == "Asia/Kolkata"
        assert "extra_field" not in out

    def test_drops_none_values(self):
        out = _profile_payload_to_dict({"age": None, "gender": "male"})
        assert out == {"gender": "male"}


class TestDeriveHasCgm:
    def test_returns_true_when_event_in_last_7d(self):
        now = datetime(2026, 4, 20, tzinfo=timezone.utc)
        recent_ms = int(now.timestamp() * 1000) - (3 * 24 * 3600 * 1000)
        assert (
            _derive_has_cgm([{"start_time": recent_ms}], now) is True
        )

    def test_returns_false_when_no_recent_events(self):
        now = datetime(2026, 4, 20, tzinfo=timezone.utc)
        old_ms = int(now.timestamp() * 1000) - (30 * 24 * 3600 * 1000)
        assert _derive_has_cgm([{"start_time": old_ms}], now) is False

    def test_empty_returns_false(self):
        assert _derive_has_cgm([], datetime.utcnow()) is False


@pytest.mark.asyncio
class TestQdrantLoaderCalls:
    async def test_load_meals_requests_meal_type(self, patient_id, local_now):
        qdrant = MagicMock()
        qdrant.retrieve_filtered = AsyncMock(return_value=[])
        loader = _make_loader(qdrant=qdrant)
        await loader._load_meals(
            patient_id, local_now.date().replace(day=1), local_now.date()
        )
        req = qdrant.retrieve_filtered.call_args.args[0]
        assert req.data_types == [MEAL_DATA_TYPE]
        assert req.patient_ids == [patient_id]

    async def test_load_profile_requests_profile(self, patient_id):
        qdrant = MagicMock()
        qdrant.retrieve_filtered = AsyncMock(return_value=[])
        loader = _make_loader(qdrant=qdrant)
        await loader._load_profile(patient_id)
        req = qdrant.retrieve_filtered.call_args.args[0]
        assert req.data_types == [PROFILE_DATA_TYPE]

    async def test_load_diet_plan_requests_diet_plan(self, patient_id, local_now):
        qdrant = MagicMock()
        qdrant.retrieve_filtered = AsyncMock(return_value=[])
        loader = _make_loader(qdrant=qdrant)
        await loader._load_active_diet_plan(patient_id, local_now.date())
        req = qdrant.retrieve_filtered.call_args.args[0]
        assert req.data_types == [DIET_PLAN_DATA_TYPE]

    async def test_load_diet_plan_picks_active_only(self, patient_id, local_now):
        qdrant = MagicMock()
        qdrant.retrieve_filtered = AsyncMock(
            return_value=[
                RetrievalResult(
                    payload={"data_type": "diet_plan", "plan_status": "INACTIVE", "content": {}},
                    source="qdrant_filtered",
                    data_type="diet_plan",
                ),
                RetrievalResult(
                    payload={
                        "data_type": "diet_plan",
                        "plan_status": "ACTIVE",
                        "start_time": 2000,
                        "content": {"meals": []},
                    },
                    source="qdrant_filtered",
                    data_type="diet_plan",
                ),
            ]
        )
        loader = _make_loader(qdrant=qdrant)
        plan = await loader._load_active_diet_plan(patient_id, local_now.date())
        assert plan is not None
        assert plan["plan_status"] == "ACTIVE"

    async def test_load_cgm_events_queries_all_event_types(self, patient_id, local_now):
        qdrant = MagicMock()
        qdrant.retrieve_filtered = AsyncMock(return_value=[])
        loader = _make_loader(qdrant=qdrant)
        await loader._load_cgm_events(
            patient_id, local_now.date().replace(day=1), local_now.date()
        )
        req = qdrant.retrieve_filtered.call_args.args[0]
        assert set(req.data_types) == set(CGM_EVENT_TYPES)

    async def test_load_medications_queries_medication(self, patient_id):
        qdrant = MagicMock()
        qdrant.retrieve_filtered = AsyncMock(return_value=[])
        loader = _make_loader(qdrant=qdrant)
        await loader._load_medications(patient_id)
        req = qdrant.retrieve_filtered.call_args.args[0]
        assert req.data_types == [MEDICATION_DATA_TYPE]

    async def test_load_recent_workouts_queries_patient_workout(
        self, patient_id, local_now
    ):
        qdrant = MagicMock()
        qdrant.retrieve_filtered = AsyncMock(return_value=[])
        loader = _make_loader(qdrant=qdrant)
        await loader._load_recent_workouts(patient_id, local_now, local_now)
        req = qdrant.retrieve_filtered.call_args.args[0]
        assert req.data_types == [WORKOUT_DATA_TYPE]


@pytest.mark.asyncio
class TestLoadIntegration:
    async def test_gathers_all_loaders(self, patient_id, local_now):
        loader = _make_loader()
        with patch.object(
            loader, "_load_meals", AsyncMock(return_value=[{"m": 1}])
        ), patch.object(
            loader, "_load_profile", AsyncMock(return_value={"age": 42})
        ), patch.object(
            loader,
            "_load_active_diet_plan",
            AsyncMock(return_value={"plan_status": "ACTIVE"}),
        ), patch.object(
            loader, "_load_cgm_events", AsyncMock(return_value=[])
        ), patch.object(
            loader, "_load_medications", AsyncMock(return_value=[])
        ), patch.object(
            loader, "_load_recent_workouts", AsyncMock(return_value=[])
        ):
            ctx = await loader.load(patient_id=patient_id, local_now=local_now)

        assert ctx.patient_id == patient_id
        assert ctx.recent_meals == [{"m": 1}]
        assert ctx.profile == {"age": 42}
        assert ctx.active_diet_plan == {"plan_status": "ACTIVE"}
        assert ctx.has_cgm is False  # no CGM events

    async def test_one_loader_failing_does_not_break_others(
        self, patient_id, local_now
    ):
        loader = _make_loader()
        with patch.object(
            loader, "_load_meals", AsyncMock(side_effect=RuntimeError("qdrant down"))
        ), patch.object(
            loader, "_load_profile", AsyncMock(return_value={})
        ), patch.object(
            loader, "_load_active_diet_plan", AsyncMock(return_value=None)
        ), patch.object(
            loader, "_load_cgm_events", AsyncMock(return_value=[])
        ), patch.object(
            loader, "_load_medications", AsyncMock(return_value=[])
        ), patch.object(
            loader, "_load_recent_workouts", AsyncMock(return_value=[])
        ):
            ctx = await loader.load(patient_id=patient_id, local_now=local_now)

        assert ctx.recent_meals == []
        assert ctx.has_cgm is False
