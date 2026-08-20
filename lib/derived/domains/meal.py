"""Meal report domain — first domain inside the drain (spec §5, slice 2).

Meal vectors are per-entity (keyed by meal_id) and keep their own enqueue at
the write path; the drain owns only the daily report. No persisted rollups —
range/month meal views are computed on read from the daily docs.
"""

from __future__ import annotations

from datetime import date

from lib.derived.registry import DataDomain


class MealReportDomain:
    domain = DataDomain.MEAL

    async def compute_daily(self, patient_id: str, day: date) -> None:
        from lib.dependencies.service_dependencies import (
            get_meal_report_service,
            get_meal_stats_processor,
        )

        report = await get_meal_stats_processor().get_meal_report_by_date(patient_id, day)
        await get_meal_report_service().save_report(
            patient_id,
            {
                "patient_id": patient_id,
                "report_type": "daily",
                **report.model_dump(),
            },
        )
