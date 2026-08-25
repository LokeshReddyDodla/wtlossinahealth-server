"""Persistence and deterministic rules for canonical Body Composition data."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import status
from sqlalchemy import select

from lib.core.postgres_store import PostgresStore
from lib.models.patient_body_composition_record import (
    PatientBodyCompositionRecord,
)
from lib.schemas.body_composition import (
    BodyCompositionExtraction,
    IngestChannel,
)
from lib.utils.http_exceptions import raise_http_exception

_ALIASES = {
    "smm": "skeletal_muscle_mass",
    "pbf": "percent_body_fat",
    "body_fat_percentage": "percent_body_fat",
    "bfm": "body_fat_mass",
    "ecw_ratio": "ecw_tbw_ratio",
    "ecw_tbw": "ecw_tbw_ratio",
    "bmr": "basal_metabolic_rate",
}
_MASS_KEYS = {
    "weight",
    "protein",
    "minerals",
    "bone_mineral_content",
    "soft_lean_mass",
    "fat_free_mass",
    "skeletal_muscle_mass",
    "body_fat_mass",
    "body_cell_mass",
    "target_weight",
    "weight_control",
    "fat_control",
    "muscle_control",
}
_BOUNDS = {
    "weight": (10, 500),
    "skeletal_muscle_mass": (1, 150),
    "body_fat_mass": (0, 300),
    "percent_body_fat": (0, 80),
    "bmi": (5, 100),
    "ecw_tbw_ratio": (0.2, 0.7),
    "phase_angle": (0, 20),
    "visceral_fat_area": (0, 1000),
}
_MANUFACTURERS = {
    "inbody": "InBody",
    "tanita": "Tanita",
    "seca": "Seca",
    "withings": "Withings",
    "omron": "Omron",
    "evolt": "Evolt",
}


def _metric_key(value: str) -> str:
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    return _ALIASES.get(key, key)


def _manufacturer(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    clean = " ".join(value.split())
    return _MANUFACTURERS.get(clean.casefold(), clean)


def _normalize(data: BodyCompositionExtraction) -> BodyCompositionExtraction:
    normalized = data.model_copy(deep=True)
    normalized.manufacturer = _manufacturer(normalized.manufacturer)
    for measurement in normalized.measurements:
        measurement.key = _metric_key(measurement.key)
        unit = (measurement.unit or "").strip().lower()
        if measurement.key in _MASS_KEYS and unit in {
            "lb",
            "lbs",
            "pound",
            "pounds",
        }:
            measurement.value = round(measurement.value * 0.45359237, 4)
            measurement.unit = "kg"
            if measurement.reference_low is not None:
                measurement.reference_low = round(
                    measurement.reference_low * 0.45359237, 4
                )
            if measurement.reference_high is not None:
                measurement.reference_high = round(
                    measurement.reference_high * 0.45359237, 4
                )
    return normalized


def _validation_issues(
    data: BodyCompositionExtraction, *, include_confidence: bool
) -> list[str]:
    keys = [measurement.key for measurement in data.measurements]
    issues = [
        f"duplicate:{key}" for key, count in Counter(keys).items() if count > 1
    ]
    for measurement in data.measurements:
        bounds = _BOUNDS.get(measurement.key)
        if bounds and not bounds[0] <= measurement.value <= bounds[1]:
            issues.append(f"implausible:{measurement.key}")
        if include_confidence and measurement.confidence < 0.85:
            issues.append(f"low_confidence:{measurement.key}")

    available = set(keys)
    if "weight" not in available:
        issues.append("missing:weight")
    if not available.intersection(
        {
            "body_fat_mass",
            "percent_body_fat",
            "fat_free_mass",
            "soft_lean_mass",
        }
    ):
        issues.append("missing:composition_measurement")
    if include_confidence and data.extraction_confidence < 0.8:
        issues.append("low_confidence:overall")
    return sorted(set(issues))


class BodyCompositionService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    async def create_draft(
        self,
        *,
        patient_id: UUID,
        data: BodyCompositionExtraction,
        ingest_channel: IngestChannel,
        source_file_url: str,
        original_filename: str | None,
        content_type: str,
        uploaded_by_id: UUID | None,
        uploaded_by_type: str,
    ) -> dict[str, Any]:
        data = _normalize(data)
        issues = _validation_issues(data, include_confidence=True)
        test_datetime = data.test_datetime
        if test_datetime and test_datetime.tzinfo:
            test_datetime = test_datetime.replace(tzinfo=None)

        row = PatientBodyCompositionRecord(
            patient_id=patient_id,
            status="draft",
            ingest_channel=ingest_channel.value,
            manufacturer=data.manufacturer,
            device_model=data.device_model,
            measurement_method=data.measurement_method.value,
            test_datetime=test_datetime,
            source_file_url=source_file_url,
            original_filename=original_filename,
            content_type=content_type,
            data=data.model_dump(mode="json"),
            validation_issues=issues,
            extraction_confidence=data.extraction_confidence,
            uploaded_by_id=uploaded_by_id,
            uploaded_by_type=uploaded_by_type,
        )
        async with self.postgres_store.get_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._serialize(row)

    async def confirm(
        self,
        *,
        patient_id: UUID,
        record_id: UUID,
        data: BodyCompositionExtraction,
        confirmed_by_id: UUID | None,
        confirmed_by_type: str,
    ) -> dict[str, Any]:
        data = _normalize(data)
        blocking = _validation_issues(data, include_confidence=False)
        if blocking:
            raise_http_exception(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                message="Body-composition values need correction",
                detail=", ".join(blocking),
            )

        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientBodyCompositionRecord, record_id)
            if (
                not row
                or row.patient_id != patient_id
                or row.status != "draft"
            ):
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Body-composition draft not found",
                )
            test_datetime = data.test_datetime
            if test_datetime and test_datetime.tzinfo:
                test_datetime = test_datetime.replace(tzinfo=None)
            row.status = "confirmed"
            row.data = data.model_dump(mode="json")
            row.manufacturer = data.manufacturer
            row.device_model = data.device_model
            row.measurement_method = data.measurement_method.value
            row.test_datetime = test_datetime
            row.validation_issues = []
            row.confirmed_by_id = confirmed_by_id
            row.confirmed_by_type = confirmed_by_type
            row.confirmed_at = datetime.now().replace(tzinfo=None)
            await session.commit()
            await session.refresh(row)
        return self._serialize(row)

    async def list_records(
        self, patient_id: UUID, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientBodyCompositionRecord)
                .where(
                    PatientBodyCompositionRecord.patient_id == patient_id,
                    PatientBodyCompositionRecord.status != "archived",
                )
                .order_by(
                    PatientBodyCompositionRecord.test_datetime.desc().nullslast(),
                    PatientBodyCompositionRecord.created_at.desc(),
                )
                .limit(limit)
            )
            rows = result.scalars().all()
        return [self._serialize(row) for row in rows]

    async def get_record(
        self, patient_id: UUID, record_id: UUID
    ) -> dict[str, Any]:
        row = await self._get_row(patient_id, record_id)
        return self._serialize(row)

    async def get_latest(self, patient_id: UUID) -> dict[str, Any] | None:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientBodyCompositionRecord)
                .where(
                    PatientBodyCompositionRecord.patient_id == patient_id,
                    PatientBodyCompositionRecord.status == "confirmed",
                )
                .order_by(
                    PatientBodyCompositionRecord.test_datetime.desc().nullslast(),
                    PatientBodyCompositionRecord.created_at.desc(),
                )
                .limit(1)
            )
            row = result.scalars().first()
        return self._serialize(row) if row else None

    async def archive(self, patient_id: UUID, record_id: UUID) -> None:
        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientBodyCompositionRecord, record_id)
            if not row or row.patient_id != patient_id:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Body-composition record not found",
                )
            row.status = "archived"
            await session.commit()

    async def get_trends(
        self, patient_id: UUID, *, limit: int = 24
    ) -> dict[str, Any]:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientBodyCompositionRecord)
                .where(
                    PatientBodyCompositionRecord.patient_id == patient_id,
                    PatientBodyCompositionRecord.status == "confirmed",
                )
                .order_by(
                    PatientBodyCompositionRecord.test_datetime.desc().nullslast(),
                    PatientBodyCompositionRecord.created_at.desc(),
                )
                .limit(limit)
            )
            rows = list(reversed(result.scalars().all()))

        return self._compute_trends(rows)

    @staticmethod
    def _compute_trends(
        rows: list[PatientBodyCompositionRecord],
    ) -> dict[str, Any]:
        series: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            for measurement in (row.data or {}).get("measurements", []):
                series.setdefault(measurement["key"], []).append(
                    {
                        "record_id": str(row.record_id),
                        "test_datetime": row.test_datetime.isoformat()
                        if row.test_datetime
                        else None,
                        "value": measurement["value"],
                        "unit": measurement.get("unit"),
                        "measurement_method": row.measurement_method,
                        "manufacturer": row.manufacturer,
                        "device_model": row.device_model,
                    }
                )

        comparison = None
        if len(rows) >= 2:
            previous, latest = rows[-2], rows[-1]
            same_method = (
                previous.measurement_method == latest.measurement_method
            )
            comparison = {
                "comparable": same_method,
                "reason": None
                if same_method
                else "measurement_method_changed",
                "previous_method": previous.measurement_method,
                "latest_method": latest.measurement_method,
                "device_changed": (
                    previous.manufacturer != latest.manufacturer
                    or previous.device_model != latest.device_model
                ),
            }
        return {
            "record_count": len(rows),
            "series": series,
            "comparison": comparison,
        }

    async def _get_row(
        self, patient_id: UUID, record_id: UUID
    ) -> PatientBodyCompositionRecord:
        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientBodyCompositionRecord, record_id)
        if not row or row.patient_id != patient_id or row.status == "archived":
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Body-composition record not found",
            )
        return row

    @staticmethod
    def _serialize(row: PatientBodyCompositionRecord) -> dict[str, Any]:
        return {
            "record_id": str(row.record_id),
            "patient_id": str(row.patient_id),
            "status": row.status,
            "ingest_channel": row.ingest_channel,
            "manufacturer": row.manufacturer,
            "device_model": row.device_model,
            "measurement_method": row.measurement_method,
            "test_datetime": row.test_datetime.isoformat()
            if row.test_datetime
            else None,
            "source_file_url": row.source_file_url,
            "original_filename": row.original_filename,
            "data": row.data,
            "validation_issues": row.validation_issues or [],
            "created_at": row.created_at.isoformat()
            if row.created_at
            else None,
        }
