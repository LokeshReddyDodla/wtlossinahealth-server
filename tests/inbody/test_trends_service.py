"""Unit tests for InbodyTrendsService pure computation."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import lib.models  # noqa: F401  (resolves model-import cycles)
from lib.services.inbody.trends_service import InbodyTrendsService


def _row(
    report_date: str,
    *,
    weight: float | None = None,
    smm: float | None = None,
    pbf: float | None = None,
    score: int | None = None,
    created_at: str = "2026-01-01T00:00:00",
    needs_review: bool = False,
    report_id: str | None = None,
):
    measurements = []
    if weight is not None:
        measurements.append(
            {
                "name": "weight",
                "value": weight,
                "unit": "kg",
                "level": "high",
            }
        )
    if smm is not None:
        measurements.append(
            {
                "name": "skeletal_muscle_mass",
                "value": smm,
                "unit": "kg",
                "level": "normal",
            }
        )
    if pbf is not None:
        measurements.append(
            {
                "name": "percent_body_fat",
                "value": pbf,
                "unit": "%",
                "level": "high",
            }
        )
    return {
        "report_id": report_id or str(uuid4()),
        "report_date": report_date,
        "created_at": created_at,
        "needs_review": needs_review,
        "analysis": {
            "measurements": measurements,
            "inbody_score": score,
            "segmental_lean": [
                {
                    "segment": "right_arm",
                    "mass_kg": 2.6,
                    "percent_of_normal": 89.0,
                    "level": "low",
                }
            ],
            "weight_control": {"target_weight_kg": 60.0},
        },
    }


class TestCompute:
    def test_empty(self):
        result = InbodyTrendsService._compute([])
        assert result["scan_count"] == 0
        assert result["series"] == {}
        assert result["latest_vs_previous"] is None
        assert result["overall"] is None

    def test_single_scan_has_series_but_no_comparison(self):
        result = InbodyTrendsService._compute(
            [_row("2026-01-10", weight=74.4, score=61)]
        )
        assert result["scan_count"] == 1
        assert result["latest_vs_previous"] is None
        assert result["series"]["weight"]["points"][0]["value"] == 74.4
        assert result["series"]["inbody_score"]["points"][0]["value"] == 61
        assert result["overall"]["first_vs_latest"] == {}
        assert result["overall"]["latest_weight_control"] == {
            "target_weight_kg": 60.0
        }

    def test_two_scans_deltas_and_direction(self):
        rows = [
            _row("2026-01-10", weight=74.4, smm=26.7, pbf=35.9, score=61),
            _row("2026-02-10", weight=71.3, smm=26.9, pbf=33.1, score=66),
        ]
        result = InbodyTrendsService._compute(rows)
        metrics = result["latest_vs_previous"]["metrics"]

        assert metrics["weight"]["delta"] == -3.1
        assert metrics["weight"]["direction"] == "down"
        assert metrics["skeletal_muscle_mass"]["delta"] == 0.2
        assert metrics["skeletal_muscle_mass"]["direction"] == "up"
        assert metrics["inbody_score"]["delta"] == 5
        assert result["latest_vs_previous"]["days_between"] == 31
        assert metrics["weight"]["pct_change"] == pytest.approx(-4.2, abs=0.1)

    def test_series_ordered_and_flagged(self):
        rows = [
            _row("2026-02-10", weight=71.3, needs_review=True),
            _row("2026-01-10", weight=74.4),
        ]
        # _compute sorts by date regardless of input order
        result = InbodyTrendsService._compute(rows)
        points = result["series"]["weight"]["points"]
        assert [p["date"] for p in points] == ["2026-01-10", "2026-02-10"]
        assert points[1]["needs_review"] is True

    def test_duplicate_date_keeps_latest_created(self):
        stale = _row(
            "2026-01-10", weight=99.0, created_at="2026-01-10T08:00:00"
        )
        fresh = _row(
            "2026-01-10", weight=74.4, created_at="2026-01-10T09:00:00"
        )
        result = InbodyTrendsService._compute([stale, fresh])
        points = result["series"]["weight"]["points"]
        assert len(points) == 1
        assert points[0]["value"] == 74.4

    def test_segmental_series(self):
        result = InbodyTrendsService._compute([_row("2026-01-10", weight=74.4)])
        seg = result["segmental_lean"]["right_arm"]
        assert seg[0]["mass_kg"] == 2.6
        assert seg[0]["level"] == "low"

    def test_missing_metric_in_one_scan_excluded_from_deltas(self):
        rows = [
            _row("2026-01-10", weight=74.4),
            _row("2026-02-10", weight=71.3, smm=26.9),
        ]
        metrics = InbodyTrendsService._compute(rows)["latest_vs_previous"][
            "metrics"
        ]
        assert "weight" in metrics
        assert "skeletal_muscle_mass" not in metrics


class TestComputePairDeltas:
    @pytest.mark.asyncio
    async def test_first_scan_has_no_previous(self):
        service = InbodyTrendsService(postgres_store=None)
        first = _row("2026-01-10", weight=74.4)
        service._load_usable_rows = AsyncMock(return_value=[first])

        pair = await service.compute_pair_deltas(
            uuid4(), first["report_id"]
        )
        assert pair is not None
        assert pair["previous"] is None
        assert pair["deltas"] == {}

    @pytest.mark.asyncio
    async def test_pair_deltas_for_second_scan(self):
        service = InbodyTrendsService(postgres_store=None)
        first = _row("2026-01-10", weight=74.4)
        second = _row("2026-02-10", weight=71.3)
        service._load_usable_rows = AsyncMock(return_value=[first, second])

        pair = await service.compute_pair_deltas(
            uuid4(), second["report_id"]
        )
        assert pair["previous"]["report_id"] == first["report_id"]
        assert pair["deltas"]["weight"]["delta"] == -3.1

    @pytest.mark.asyncio
    async def test_unknown_report_returns_none(self):
        service = InbodyTrendsService(postgres_store=None)
        service._load_usable_rows = AsyncMock(
            return_value=[_row("2026-01-10", weight=74.4)]
        )
        assert await service.compute_pair_deltas(uuid4(), uuid4()) is None
