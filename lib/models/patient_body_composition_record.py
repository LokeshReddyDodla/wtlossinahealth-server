"""Canonical, device-neutral body-composition record.

Frequently-read metrics are promoted to typed, indexable columns (so trends,
BMIQ, and cohort/panel queries hit real columns) while the full extraction —
per-measurement labels, reference ranges, confidence, segmental, impedance, and
any vendor-specific long-tail — is preserved in JSONB. The service keeps the two
in sync (columns projected from the canonical extraction).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientBodyCompositionRecord(Base):
    __tablename__ = "patient_body_composition_records"

    record_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )

    # Lifecycle: draft · needs_review · confirmed · failed · superseded · archived
    status = Column(String, nullable=False, default="draft")
    ingest_channel = Column(String, nullable=False)

    # Provenance — vendor/model are free strings (analyzers proliferate); method
    # and channel are enums at the schema edge.
    manufacturer = Column(String, nullable=True)
    device_model = Column(String, nullable=True)
    measurement_method = Column(String, nullable=False)
    test_datetime = Column(DateTime, nullable=True)

    source_file_url = Column(String, nullable=True)
    original_filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)

    # ── Promoted, typed metric columns (projected from `data`) ───────────────
    weight_kg = Column(Float, nullable=True)
    bmi = Column(Float, nullable=True)
    obesity_degree_pct = Column(Float, nullable=True)
    device_score = Column(Float, nullable=True)
    total_body_water_l = Column(Float, nullable=True)
    intracellular_water_l = Column(Float, nullable=True)
    extracellular_water_l = Column(Float, nullable=True)
    protein_kg = Column(Float, nullable=True)
    minerals_kg = Column(Float, nullable=True)
    bone_mineral_content_kg = Column(Float, nullable=True)
    body_fat_mass_kg = Column(Float, nullable=True)
    soft_lean_mass_kg = Column(Float, nullable=True)
    fat_free_mass_kg = Column(Float, nullable=True)
    skeletal_muscle_mass_kg = Column(Float, nullable=True)
    body_cell_mass_kg = Column(Float, nullable=True)
    percent_body_fat = Column(Float, nullable=True)
    visceral_fat_level = Column(Float, nullable=True)
    visceral_fat_area_cm2 = Column(Float, nullable=True)
    waist_hip_ratio = Column(Float, nullable=True)
    waist_cm = Column(Float, nullable=True)
    hip_cm = Column(Float, nullable=True)
    ecw_tbw_ratio = Column(Float, nullable=True)
    whole_body_phase_angle_deg = Column(Float, nullable=True)
    skeletal_muscle_index = Column(Float, nullable=True)
    basal_metabolic_rate_kcal = Column(Float, nullable=True)
    # Targets / controls (may be negative)
    target_weight_kg = Column(Float, nullable=True)
    weight_control_kg = Column(Float, nullable=True)
    fat_control_kg = Column(Float, nullable=True)
    muscle_control_kg = Column(Float, nullable=True)

    # ── Full extraction + long tail (source of truth) ────────────────────────
    # `data` holds the canonical BodyCompositionExtraction (canonical measurements
    # + segmental + impedance + meta). Non-canonical vendor metrics we couldn't map
    # are kept separately so `data.measurements` stays canonical.
    data = Column(JSONB, nullable=False)
    vendor_metrics = Column(JSONB, nullable=False, default=list)
    validation_issues = Column(JSONB, nullable=False, default=list)
    extraction_confidence = Column(Float, nullable=False, default=0.0)

    # Corrections supersede an immutable confirmed record rather than mutating it.
    supersedes_id = Column(UUID(as_uuid=True), nullable=True)
    superseded_by_id = Column(UUID(as_uuid=True), nullable=True)

    uploaded_by_id = Column(UUID(as_uuid=True), nullable=True)
    uploaded_by_type = Column(String, nullable=True)
    confirmed_by_id = Column(UUID(as_uuid=True), nullable=True)
    confirmed_by_type = Column(String, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now().replace(tzinfo=None))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    patient = relationship("Patient")

    __table_args__ = (
        # Per-patient chronological reads (list / latest / trends).
        Index(
            "ix_body_composition_patient_status_date",
            "patient_id",
            "status",
            "test_datetime",
        ),
        # Cross-patient cohort / panel filters on the hottest metrics.
        Index("ix_body_composition_pbf", "status", "percent_body_fat"),
        Index("ix_body_composition_vfa", "status", "visceral_fat_area_cm2"),
        Index("ix_body_composition_smm", "status", "skeletal_muscle_mass_kg"),
        Index("ix_body_composition_ecw", "status", "ecw_tbw_ratio"),
    )
