"""Deterministic scan-over-scan trends from stored InBody extractions.

``patient_inbody_reports.analysis`` is a plain JSON column, so rows are
loaded and all computation happens in Python. The computation itself is
pure/static so it can be unit-tested without a database.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select

from lib.core.postgres_store import PostgresStore
from lib.models.patient_inbody_report import PatientInbodyReport

USABLE_STATUSES = ("extracted", "needs_review")

# Metrics surfaced in delta comparisons; series are built for every
# measurement name the extractor produced.
CANONICAL_METRICS = (
    "weight",
    "skeletal_muscle_mass",
    "body_fat_mass",
    "percent_body_fat",
    "bmi",
    "basal_metabolic_rate",
    "visceral_fat_level",
    "total_body_water",
    "ecw_ratio",
    "waist_hip_ratio",
    "phase_angle",
    "smi",
    "inbody_score",
)


class InbodyTrendsService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    async def get_trends(
        self, patient_id: UUID, limit: int = 24
    ) -> Dict[str, Any]:
        rows = await self._load_usable_rows(patient_id, limit)
        return self._compute(rows)

    async def compute_pair_deltas(
        self, patient_id: UUID, report_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Deltas between one report and the usable scan preceding it.

        Returns None when the report itself is missing or not usable;
        ``previous`` is None for a patient's first scan.
        """
        rows = await self._load_usable_rows(patient_id, limit=1000)
        rows = self._dedupe_by_date(rows)

        current_idx = next(
            (
                i
                for i, row in enumerate(rows)
                if row["report_id"] == str(report_id)
            ),
            None,
        )
        if current_idx is None:
            return None

        current = rows[current_idx]
        previous = rows[current_idx - 1] if current_idx > 0 else None

        result: Dict[str, Any] = {
            "current": {
                "report_id": current["report_id"],
                "report_date": current["report_date"],
            },
            "previous": None,
            "deltas": {},
        }
        if previous:
            result["previous"] = {
                "report_id": previous["report_id"],
                "report_date": previous["report_date"],
            }
            result["deltas"] = self._pair_deltas(previous, current)
        return result

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    async def _load_usable_rows(
        self, patient_id: UUID, limit: int
    ) -> List[Dict[str, Any]]:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientInbodyReport)
                .where(
                    PatientInbodyReport.patient_id == patient_id,
                    PatientInbodyReport.status.in_(USABLE_STATUSES),
                )
                .order_by(
                    PatientInbodyReport.report_date.desc(),
                    PatientInbodyReport.created_at.desc(),
                )
                .limit(limit)
            )
            rows = result.scalars().all()

        # Loaded newest-first for the LIMIT; trends read oldest-first.
        return [
            {
                "report_id": str(row.report_id),
                "report_date": row.report_date.isoformat()
                if row.report_date
                else None,
                "created_at": row.created_at.isoformat()
                if row.created_at
                else "",
                "needs_review": row.status == "needs_review",
                "analysis": row.analysis or {},
            }
            for row in reversed(rows)
        ]

    # ------------------------------------------------------------------
    # Pure computation
    # ------------------------------------------------------------------

    @classmethod
    def _compute(cls, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        rows = cls._dedupe_by_date(rows)

        if not rows:
            return {
                "scan_count": 0,
                "series": {},
                "segmental_lean": {},
                "latest_vs_previous": None,
                "overall": None,
            }

        series = cls._build_series(rows)
        segmental = cls._build_segmental_series(rows)

        latest_vs_previous = None
        if len(rows) >= 2:
            previous, latest = rows[-2], rows[-1]
            latest_vs_previous = {
                "previous_report": {
                    "report_id": previous["report_id"],
                    "report_date": previous["report_date"],
                },
                "latest_report": {
                    "report_id": latest["report_id"],
                    "report_date": latest["report_date"],
                },
                "days_between": cls._days_between(
                    previous["report_date"], latest["report_date"]
                ),
                "metrics": cls._pair_deltas(previous, latest),
            }

        first, latest = rows[0], rows[-1]
        overall = {
            "scan_count": len(rows),
            "first_report_date": first["report_date"],
            "latest_report_date": latest["report_date"],
            "days_span": cls._days_between(
                first["report_date"], latest["report_date"]
            ),
            "first_vs_latest": cls._pair_deltas(first, latest)
            if len(rows) >= 2
            else {},
            "latest_weight_control": (latest["analysis"] or {}).get(
                "weight_control"
            ),
        }

        return {
            "scan_count": len(rows),
            "series": series,
            "segmental_lean": segmental,
            "latest_vs_previous": latest_vs_previous,
            "overall": overall,
        }

    @staticmethod
    def _dedupe_by_date(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """One scan per report_date — a re-upload of the same sheet must not
        double-count in series; the most recently created row wins."""
        by_date: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = row.get("report_date") or ""
            existing = by_date.get(key)
            if not existing or row.get("created_at", "") >= existing.get(
                "created_at", ""
            ):
                by_date[key] = row
        return sorted(by_date.values(), key=lambda r: r.get("report_date") or "")

    @classmethod
    def _build_series(
        cls, rows: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        series: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            for name, entry in cls._metric_values(row).items():
                metric_series = series.setdefault(
                    name, {"unit": entry.get("unit"), "points": []}
                )
                if metric_series["unit"] is None and entry.get("unit"):
                    metric_series["unit"] = entry["unit"]
                metric_series["points"].append(
                    {
                        "report_id": row["report_id"],
                        "date": row["report_date"],
                        "value": entry["value"],
                        "level": entry.get("level"),
                        "needs_review": row.get("needs_review", False),
                    }
                )
        return series

    @staticmethod
    def _build_segmental_series(
        rows: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        segmental: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            for seg in (row["analysis"] or {}).get("segmental_lean") or []:
                segment = seg.get("segment")
                if not segment:
                    continue
                segmental.setdefault(segment, []).append(
                    {
                        "report_id": row["report_id"],
                        "date": row["report_date"],
                        "mass_kg": seg.get("mass_kg"),
                        "percent_of_normal": seg.get("percent_of_normal"),
                        "level": seg.get("level"),
                    }
                )
        return segmental

    @classmethod
    def _pair_deltas(
        cls, previous: Dict[str, Any], latest: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        prev_values = cls._metric_values(previous)
        latest_values = cls._metric_values(latest)

        deltas: Dict[str, Dict[str, Any]] = {}
        for name in CANONICAL_METRICS:
            prev_entry = prev_values.get(name)
            latest_entry = latest_values.get(name)
            if not prev_entry or not latest_entry:
                continue
            prev_value = prev_entry["value"]
            latest_value = latest_entry["value"]
            delta = round(latest_value - prev_value, 2)
            deltas[name] = {
                "unit": latest_entry.get("unit") or prev_entry.get("unit"),
                "previous": prev_value,
                "latest": latest_value,
                "delta": delta,
                "pct_change": round(delta / prev_value * 100, 1)
                if prev_value
                else None,
                "direction": "up"
                if delta > 0
                else "down"
                if delta < 0
                else "flat",
            }
        return deltas

    @staticmethod
    def _metric_values(row: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Flatten one row's analysis into {metric_name: {value, unit, level}}."""
        analysis = row.get("analysis") or {}
        values: Dict[str, Dict[str, Any]] = {}
        for measurement in analysis.get("measurements") or []:
            name = measurement.get("name")
            value = measurement.get("value")
            if not name or not isinstance(value, (int, float)):
                continue
            values[name] = {
                "value": value,
                "unit": measurement.get("unit"),
                "level": measurement.get("level"),
            }
        score = analysis.get("inbody_score")
        if isinstance(score, (int, float)):
            values["inbody_score"] = {
                "value": score,
                "unit": "points",
                "level": None,
            }
        return values

    @staticmethod
    def _days_between(
        start: Optional[str], end: Optional[str]
    ) -> Optional[int]:
        if not start or not end:
            return None
        from datetime import date

        try:
            return (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            return None
