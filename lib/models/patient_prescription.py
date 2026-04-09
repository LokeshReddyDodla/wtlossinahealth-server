"""Prescription model — record of what a doctor prescribed."""

import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientPrescription(Base):
    __tablename__ = "patient_prescriptions"

    prescription_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )

    doctor_name = Column(String, nullable=True)
    prescription_date = Column(Date, nullable=True)
    file_urls = Column(JSONB, nullable=False, default=list)

    status = Column(String, nullable=False, default="draft")

    extracted_data = Column(JSONB, nullable=True)

    uploaded_by_id = Column(UUID(as_uuid=True), nullable=True)
    uploaded_by_type = Column(String, nullable=True)

    follow_up_required = Column(Boolean, nullable=False, default=False)
    follow_up_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    patient = relationship("Patient", back_populates="prescriptions")
    medications = relationship(
        "PatientMedication",
        back_populates="prescription",
        cascade="all, delete",
    )

    __table_args__ = (
        Index("ix_prescription_patient_status", "patient_id", "status"),
    )
