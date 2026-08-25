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
    status: str
    ingest_channel: IngestChannel
    manufacturer: str | None = None
    device_model: str | None = None
    measurement_method: MeasurementMethod
    test_datetime: datetime | None = None
    source_file_url: str | None = None
    original_filename: str | None = None
    data: BodyCompositionExtraction
    validation_issues: list[str] = Field(default_factory=list)
    created_at: datetime
