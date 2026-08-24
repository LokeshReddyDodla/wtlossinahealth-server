"""Canonical, device-neutral body-composition record."""

import uuid
from datetime import datetime

from sqlalchemy import UUID, Column, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientBodyCompositionRecord(Base):
    __tablename__ = "patient_body_composition_records"

    record_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String, nullable=False, default="draft")
    ingest_channel = Column(String, nullable=False)

    manufacturer = Column(String, nullable=True)
    device_model = Column(String, nullable=True)
    measurement_method = Column(String, nullable=False)
    test_datetime = Column(DateTime, nullable=True)

    source_file_url = Column(String, nullable=True)
    original_filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)

    # Canonical BodyCompositionExtraction JSON. Drafts can be replaced with
    # provider-reviewed values during confirmation.
    data = Column(JSONB, nullable=False)
    validation_issues = Column(JSONB, nullable=False, default=list)
    extraction_confidence = Column(Float, nullable=False, default=0.0)

    uploaded_by_id = Column(UUID(as_uuid=True), nullable=True)
    uploaded_by_type = Column(String, nullable=True)
    confirmed_by_id = Column(UUID(as_uuid=True), nullable=True)
    confirmed_by_type = Column(String, nullable=True)
    confirmed_at = Column(DateTime, nullable=True)

    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    patient = relationship("Patient")

    __table_args__ = (
        Index(
            "ix_body_composition_patient_status_date",
            "patient_id",
            "status",
            "test_datetime",
        ),
    )
