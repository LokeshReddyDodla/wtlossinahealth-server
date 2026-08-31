"""Persistence and deterministic rules for canonical Body Composition data.

Normalization, validation, and column projection all route through the metric
registry (`metrics.py`) so a metric is defined once and flows everywhere. Records
follow a confidence-gated lifecycle: an upload lands as `confirmed` only when the
extraction is trustworthy and clean, otherwise `needs_review`; `failed` when there
is nothing usable. Confirmed records are immutable — corrections supersede them.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import status
from sqlalchemy import and_, or_, select

from lib.core.postgres_store import PostgresStore
from lib.models.patient_body_composition_record import (
    PatientBodyCompositionRecord,
)
from lib.schemas.body_composition import (
    BodyCompositionExtraction,
    BodyCompositionMeasurement,
    IngestChannel,
    RecordStatus,
)
from lib.services.body_composition import concern
from lib.services.body_composition.metrics import (
    CANONICAL_KEYS,
    SPEC_BY_KEY,
    canonical_key,
    convert_to_canonical_unit,
)
from lib.utils.http_exceptions import raise_http_exception

logger = logging.getLogger(__name__)

# An upload auto-confirms only above this whole-extraction confidence and with no
# blocking issues; anything weaker routes to a human via needs_review.
_AUTO_CONFIRM_CONFIDENCE = 0.9
_FIELD_CONFIDENCE_MIN = 0.85

_MANUFACTURERS = {
    "inbody": "InBody",
    "tanita": "Tanita",
    "seca": "Seca",
    "withings": "Withings",
    "omron": "Omron",
    "evolt": "Evolt",
}
_COMPOSITION_KEYS = frozenset(
    {"body_fat_mass", "percent_body_fat", "fat_free_mass", "soft_lean_mass"}
)


def _manufacturer(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    clean = " ".join(value.split())
    return _MANUFACTURERS.get(clean.casefold(), clean)


def _naive(value: datetime | None) -> datetime | None:
    if value and value.tzinfo:
        return value.replace(tzinfo=None)
    return value


def _normalize(
    data: BodyCompositionExtraction,
) -> tuple[BodyCompositionExtraction, list[BodyCompositionMeasurement]]:
    """Canonicalize keys/units and split unmappable vendor metrics out.

    Returns the extraction with canonical measurements only, plus the long tail of
    measurements we couldn't map to a canonical key (kept for audit, not projected).
    """
    normalized = data.model_copy(deep=True)
    normalized.manufacturer = _manufacturer(normalized.manufacturer)
    normalized.test_datetime = _naive(normalized.test_datetime)

    canonical: list[BodyCompositionMeasurement] = []
    vendor: list[BodyCompositionMeasurement] = []
    for measurement in normalized.measurements:
        key = canonical_key(measurement.key)
        measurement.key = key
        if key not in CANONICAL_KEYS:
            vendor.append(measurement)
            continue
        spec = SPEC_BY_KEY[key]
        source_unit = measurement.unit
        measurement.value, measurement.unit = convert_to_canonical_unit(
            spec, measurement.value, source_unit
        )
        if measurement.reference_low is not None:
            measurement.reference_low, _ = convert_to_canonical_unit(
                spec, measurement.reference_low, source_unit
            )
        if measurement.reference_high is not None:
            measurement.reference_high, _ = convert_to_canonical_unit(
                spec, measurement.reference_high, source_unit
            )
        canonical.append(measurement)

    normalized.measurements = canonical
    return normalized, vendor


def _validation_issues(
    data: BodyCompositionExtraction, *, include_confidence: bool
) -> list[str]:
    keys = [m.key for m in data.measurements]
    issues = [f"duplicate:{k}" for k, n in Counter(keys).items() if n > 1]
    for m in data.measurements:
        spec = SPEC_BY_KEY[m.key]
        low = spec.low if spec.signed else max(spec.low, 0)
        if not low <= m.value <= spec.high:
            issues.append(f"implausible:{m.key}")
        if include_confidence and m.confidence < _FIELD_CONFIDENCE_MIN:
            issues.append(f"low_confidence:{m.key}")

    available = set(keys)
    if "weight" not in available:
        issues.append("missing:weight")
    if not available & _COMPOSITION_KEYS:
        issues.append("missing:composition_measurement")
    if _naive(data.test_datetime) and data.test_datetime > datetime.now():
        issues.append("invalid:test_datetime_future")
    if include_confidence and data.extraction_confidence < _AUTO_CONFIRM_CONFIDENCE:
        issues.append("low_confidence:overall")
    return sorted(set(issues))


def _project_columns(data: BodyCompositionExtraction) -> dict[str, float]:
    """Canonical measurements → {typed column: value} (last value wins on dup)."""
    return {
        SPEC_BY_KEY[m.key].column: m.value
        for m in data.measurements
        if m.key in CANONICAL_KEYS
    }


class BodyCompositionService:
    def __init__(self, postgres_store: PostgresStore) -> None:
        self.postgres_store = postgres_store

    async def _enqueue_vector(self, patient_id: UUID, record_id: UUID) -> None:
        try:
            from lib.workers.tasks.body_composition.vector_generation import (
                enqueue_body_composition_vector,
            )

            await enqueue_body_composition_vector(str(patient_id), str(record_id))
        except Exception:
            logger.exception("Failed to enqueue body-composition vector for %s", record_id)

    async def _enqueue_vector_delete(self, record_id: UUID) -> None:
        try:
            from lib.workers.tasks.body_composition.vector_generation import (
                enqueue_delete_body_composition_vector,
            )

            await enqueue_delete_body_composition_vector(str(record_id))
        except Exception:
            logger.exception("Failed to enqueue body-composition vector delete for %s", record_id)

    async def _sync_profile_weight(self, patient_id: UUID, record_id: UUID) -> None:
        """Mirror the vitals path: a scan's weight is a real measurement, so the
        profile's weight (and thus BMI everywhere) follows it — but only when this
        scan is the patient's newest, so a backdated historical upload can't clobber
        the current weight."""
        try:
            latest = await self._latest_confirmed(patient_id)
            if not latest or latest.record_id != record_id or latest.weight_kg is None:
                return
            from lib.utils.sync_profile_weight import sync_profile_weight

            await sync_profile_weight(str(patient_id), float(latest.weight_kg))
        except Exception:
            logger.exception("Failed to sync profile weight from body composition %s", record_id)

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
        content_hash: str | None = None,
    ) -> dict[str, Any]:
        data, vendor = _normalize(data)
        blocking = _validation_issues(data, include_confidence=False)
        issues = _validation_issues(data, include_confidence=True)

        duplicate = await self._find_duplicate(
            patient_id, data.test_datetime, data.manufacturer, content_hash
        )
        if duplicate:
            return {**self._serialize(duplicate), "duplicate": True}

        if not data.measurements:
            record_status = RecordStatus.FAILED
        elif blocking or issues:
            record_status = RecordStatus.NEEDS_REVIEW
        else:
            record_status = RecordStatus.CONFIRMED

        row = PatientBodyCompositionRecord(
            patient_id=patient_id,
            status=record_status.value,
            ingest_channel=ingest_channel.value,
            manufacturer=data.manufacturer,
            device_model=data.device_model,
            measurement_method=data.measurement_method.value,
            test_datetime=data.test_datetime,
            source_file_url=source_file_url,
            original_filename=original_filename,
            content_type=content_type,
            data=data.model_dump(mode="json"),
            vendor_metrics=[m.model_dump(mode="json") for m in vendor],
            validation_issues=issues,
            extraction_confidence=data.extraction_confidence,
            content_hash=content_hash,
            uploaded_by_id=uploaded_by_id,
            uploaded_by_type=uploaded_by_type,
        )
        for column, value in _project_columns(data).items():
            setattr(row, column, value)
        if record_status is RecordStatus.CONFIRMED:
            row.confirmed_by_id = uploaded_by_id
            row.confirmed_by_type = uploaded_by_type
            row.confirmed_at = datetime.now().replace(tzinfo=None)

        async with self.postgres_store.get_session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        if record_status is RecordStatus.CONFIRMED:
            await self._enqueue_vector(patient_id, row.record_id)
            await self._sync_profile_weight(patient_id, row.record_id)
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
        # A reviewer's confirm is the authoritative override: validation only
        # routes extractions to review (create_draft), it never blocks the human
        # sign-off — else duplicate/implausible flags the CP can't edit away in
        # the UI would strand the record in needs_review forever.
        data, vendor = _normalize(data)

        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientBodyCompositionRecord, record_id)
            if (
                not row
                or row.patient_id != patient_id
                or row.status
                not in {RecordStatus.DRAFT.value, RecordStatus.NEEDS_REVIEW.value}
            ):
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Body-composition record is not awaiting review",
                )
            self._apply_extraction(row, data, vendor)
            row.status = RecordStatus.CONFIRMED.value
            row.validation_issues = []
            row.confirmed_by_id = confirmed_by_id
            row.confirmed_by_type = confirmed_by_type
            row.confirmed_at = datetime.now().replace(tzinfo=None)
            await session.commit()
            await session.refresh(row)
        await self._enqueue_vector(patient_id, record_id)
        await self._sync_profile_weight(patient_id, record_id)
        return self._serialize(row)

    async def supersede(
        self,
        *,
        patient_id: UUID,
        record_id: UUID,
        data: BodyCompositionExtraction,
        confirmed_by_id: UUID | None,
        confirmed_by_type: str,
    ) -> dict[str, Any]:
        """Correct a confirmed record by replacing it — the original stays intact."""
        data, vendor = _normalize(data)

        now = datetime.now().replace(tzinfo=None)
        async with self.postgres_store.get_session() as session:
            old = await session.get(PatientBodyCompositionRecord, record_id)
            if (
                not old
                or old.patient_id != patient_id
                or old.status != RecordStatus.CONFIRMED.value
            ):
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Confirmed body-composition record not found",
                )
            new = PatientBodyCompositionRecord(
                patient_id=patient_id,
                status=RecordStatus.CONFIRMED.value,
                ingest_channel=old.ingest_channel,
                source_file_url=old.source_file_url,
                original_filename=old.original_filename,
                content_type=old.content_type,
                uploaded_by_id=old.uploaded_by_id,
                uploaded_by_type=old.uploaded_by_type,
                confirmed_by_id=confirmed_by_id,
                confirmed_by_type=confirmed_by_type,
                confirmed_at=now,
                supersedes_id=old.record_id,
            )
            self._apply_extraction(new, data, vendor)
            new.validation_issues = []
            session.add(new)
            await session.flush()
            old.status = RecordStatus.SUPERSEDED.value
            old.superseded_by_id = new.record_id
            await session.commit()
            await session.refresh(new)
            new_id = new.record_id
        await self._enqueue_vector(patient_id, new_id)
        await self._enqueue_vector_delete(record_id)
        await self._sync_profile_weight(patient_id, new_id)
        return self._serialize(new)

    async def list_records(
        self, patient_id: UUID, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientBodyCompositionRecord)
                .where(
                    PatientBodyCompositionRecord.patient_id == patient_id,
                    PatientBodyCompositionRecord.status.notin_(
                        (
                            RecordStatus.ARCHIVED.value,
                            RecordStatus.SUPERSEDED.value,
                        )
                    ),
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
        row = await self._latest_confirmed(patient_id)
        return self._serialize(row) if row else None

    async def get_latest_metrics(
        self, patient_id: UUID
    ) -> dict[str, float] | None:
        """Flattened canonical metrics from the latest confirmed record — for BMIQ."""
        row = await self._latest_confirmed(patient_id)
        return self._metrics(row) if row else None

    async def archive(self, patient_id: UUID, record_id: UUID) -> None:
        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientBodyCompositionRecord, record_id)
            if not row or row.patient_id != patient_id:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Body-composition record not found",
                )
            row.status = RecordStatus.ARCHIVED.value
            await session.commit()
        await self._enqueue_vector_delete(record_id)

    async def get_trends(
        self, patient_id: UUID, *, limit: int = 24
    ) -> dict[str, Any]:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientBodyCompositionRecord)
                .where(
                    PatientBodyCompositionRecord.patient_id == patient_id,
                    PatientBodyCompositionRecord.status
                    == RecordStatus.CONFIRMED.value,
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
            when = row.test_datetime.isoformat() if row.test_datetime else None
            for key, spec in SPEC_BY_KEY.items():
                value = getattr(row, spec.column)
                if value is None:
                    continue
                series.setdefault(key, []).append(
                    {
                        "record_id": str(row.record_id),
                        "test_datetime": when,
                        "value": value,
                        "unit": spec.unit,
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
                "reason": None if same_method else "measurement_method_changed",
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

    @staticmethod
    def _apply_extraction(
        row: PatientBodyCompositionRecord,
        data: BodyCompositionExtraction,
        vendor: list[BodyCompositionMeasurement],
    ) -> None:
        row.manufacturer = data.manufacturer
        row.device_model = data.device_model
        row.measurement_method = data.measurement_method.value
        row.test_datetime = data.test_datetime
        row.data = data.model_dump(mode="json")
        row.vendor_metrics = [m.model_dump(mode="json") for m in vendor]
        row.extraction_confidence = data.extraction_confidence
        for spec in SPEC_BY_KEY.values():
            setattr(row, spec.column, None)
        for column, value in _project_columns(data).items():
            setattr(row, column, value)

    async def _find_duplicate(
        self,
        patient_id: UUID,
        test_datetime: datetime | None,
        manufacturer: str | None,
        content_hash: str | None,
    ) -> PatientBodyCompositionRecord | None:
        """An active scan that is the same as this upload — matched by clinical
        identity (patient + test time + manufacturer) or, when the report prints
        no test date, by source-file hash."""
        conditions = []
        if test_datetime is not None:
            conditions.append(
                and_(
                    PatientBodyCompositionRecord.test_datetime == test_datetime,
                    PatientBodyCompositionRecord.manufacturer == manufacturer,
                )
            )
        if content_hash:
            conditions.append(
                PatientBodyCompositionRecord.content_hash == content_hash
            )
        if not conditions:
            return None
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientBodyCompositionRecord)
                .where(
                    PatientBodyCompositionRecord.patient_id == patient_id,
                    PatientBodyCompositionRecord.status.in_(
                        (
                            RecordStatus.DRAFT.value,
                            RecordStatus.NEEDS_REVIEW.value,
                            RecordStatus.CONFIRMED.value,
                        )
                    ),
                    or_(*conditions),
                )
                .limit(1)
            )
            return result.scalars().first()

    async def _latest_confirmed(
        self, patient_id: UUID
    ) -> PatientBodyCompositionRecord | None:
        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(PatientBodyCompositionRecord)
                .where(
                    PatientBodyCompositionRecord.patient_id == patient_id,
                    PatientBodyCompositionRecord.status
                    == RecordStatus.CONFIRMED.value,
                )
                .order_by(
                    PatientBodyCompositionRecord.test_datetime.desc().nullslast(),
                    PatientBodyCompositionRecord.created_at.desc(),
                )
                .limit(1)
            )
            return result.scalars().first()

    async def _get_row(
        self, patient_id: UUID, record_id: UUID
    ) -> PatientBodyCompositionRecord:
        async with self.postgres_store.get_session() as session:
            row = await session.get(PatientBodyCompositionRecord, record_id)
        if (
            not row
            or row.patient_id != patient_id
            or row.status == RecordStatus.ARCHIVED.value
        ):
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Body-composition record not found",
            )
        return row

    @staticmethod
    def _metrics(row: PatientBodyCompositionRecord) -> dict[str, float]:
        return {
            key: getattr(row, spec.column)
            for key, spec in SPEC_BY_KEY.items()
            if getattr(row, spec.column) is not None
        }

    @classmethod
    def _serialize(cls, row: PatientBodyCompositionRecord) -> dict[str, Any]:
        data = dict(row.data or {})
        if isinstance(data.get("measurements"), list):
            data["measurements"] = concern.annotate(data["measurements"])
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
            "metrics": cls._metrics(row),
            "data": data,
            "segmental": data.get("segmental", []),
            "vendor_metrics": row.vendor_metrics or [],
            "validation_issues": row.validation_issues or [],
            "extraction_confidence": row.extraction_confidence,
            "supersedes_id": str(row.supersedes_id)
            if row.supersedes_id
            else None,
            "superseded_by_id": str(row.superseded_by_id)
            if row.superseded_by_id
            else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
