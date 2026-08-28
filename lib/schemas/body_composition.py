"""Device-neutral Body Composition contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MeasurementMethod(str, Enum):
    BIA_MULTIFREQUENCY = "bia_multifrequency"
    BIA_SINGLE_FREQUENCY = "bia_single_frequency"
    DXA = "dxa"
    ADP = "adp"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class IngestChannel(str, Enum):
    CARE_PROVIDER_UPLOAD = "care_provider_upload"
    PATIENT_UPLOAD = "patient_upload"
    API_SYNC = "api_sync"
    MANUAL = "manual"
    MIGRATION = "migration"


class RecordStatus(str, Enum):
    DRAFT = "draft"                 # extracted, not yet trusted
    NEEDS_REVIEW = "needs_review"   # low confidence / soft issues — provider must confirm
    CONFIRMED = "confirmed"         # clinical record, immutable (corrections supersede)
    FAILED = "failed"              # unreadable / no usable measurements
    SUPERSEDED = "superseded"      # replaced by a corrected record
    ARCHIVED = "archived"          # soft-deleted


class BodyRegion(str, Enum):
    RIGHT_ARM = "right_arm"
    LEFT_ARM = "left_arm"
    TRUNK = "trunk"
    RIGHT_LEG = "right_leg"
    LEFT_LEG = "left_leg"


class BodyCompositionMeasurement(BaseModel):
    key: str = Field(description="Canonical snake_case metric key")
    label: str | None = Field(
        None, description="Source label when it adds useful vendor context"
    )
    value: float
    unit: str | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    confidence: float = Field(ge=0, le=1)
    position: str | None = Field(
        None, description="above | in_range | below vs the printed range; null if none"
    )
    concern: str | None = Field(
        None, description="none | alert — whether the position warrants attention"
    )


class SegmentalComposition(BaseModel):
    region: BodyRegion
    lean_mass_kg: float | None = None
    lean_percent_reference: float | None = None
    fat_mass_kg: float | None = None
    fat_percent_reference: float | None = None
    confidence: float = Field(ge=0, le=1)


class ImpedanceMeasurement(BaseModel):
    frequency_khz: float = Field(gt=0)
    region: BodyRegion
    resistance_ohm: float | None = Field(None, gt=0)
    reactance_ohm: float | None = Field(None, gt=0)
    confidence: float = Field(ge=0, le=1)


class BodyCompositionExtraction(BaseModel):
    test_datetime: datetime | None = None
    manufacturer: str | None = None
    device_model: str | None = None
    measurement_method: MeasurementMethod = MeasurementMethod.UNKNOWN
    measurements: list[BodyCompositionMeasurement] = Field(
        default_factory=list
    )
    segmental: list[SegmentalComposition] = Field(default_factory=list)
    impedance: list[ImpedanceMeasurement] = Field(default_factory=list)
    extraction_confidence: float = Field(ge=0, le=1)
    notes: str | None = None


class ConfirmBodyCompositionRequest(BaseModel):
    record_id: str
    data: BodyCompositionExtraction


class BodyCompositionRecordResponse(BaseModel):
    record_id: str
    patient_id: str
    status: RecordStatus
    ingest_channel: IngestChannel
    manufacturer: str | None = None
    device_model: str | None = None
    measurement_method: MeasurementMethod
    test_datetime: datetime | None = None
    source_file_url: str | None = None
    original_filename: str | None = None
    # Flattened canonical metric → value (in canonical units), from typed columns —
    # the shape the frontend and BMIQ read directly.
    metrics: dict[str, float] = Field(default_factory=dict)
    data: BodyCompositionExtraction
    segmental: list[SegmentalComposition] = Field(default_factory=list)
    vendor_metrics: list[BodyCompositionMeasurement] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    extraction_confidence: float = 0.0
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    created_at: datetime
