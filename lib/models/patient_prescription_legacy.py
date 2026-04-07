"""Legacy prescription models — kept for backward compatibility.

Tables renamed to *_legacy in migration.
New code should use PatientPrescription from patient_prescription.py
and PatientMedication from patient_medication.py instead.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientPrescriptionMedicineLegacy(Base):
    __tablename__ = "patient_prescription_medicines_legacy"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    prescription_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "patient_prescriptions_legacy.prescription_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    brand_name = Column(String, nullable=True)
    generic_name = Column(String, nullable=True)
    formulation = Column(String, nullable=True)
    strength = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    before_after_food = Column(String, nullable=True)
    route = Column(String, nullable=True)
    instructions = Column(Text, nullable=True)
    purpose = Column(Text, nullable=True)
    possible_side_effects = Column(JSONB, nullable=True)
    explanation = Column(Text, nullable=False)

    prescription = relationship(
        "PatientPrescriptionLegacy", back_populates="medicines"
    )


class PatientPrescriptionLegacy(Base):
    __tablename__ = "patient_prescriptions_legacy"

    prescription_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )

    patient = relationship("Patient", back_populates="prescriptions_legacy")

    doctor_name = Column(String, nullable=False)
    prescription_date = Column(String, nullable=False)
    prescription_file_url = Column(Text, nullable=False)

    analyzed = Column(Boolean, default=True, nullable=False)
    source = Column(String, default="ai", nullable=False)

    general_advice = Column(Text, nullable=True)
    follow_up_required = Column(Boolean, default=False)
    follow_up_in_days = Column(Integer, nullable=True)
    overall_summary = Column(Text, nullable=True)

    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    medicines = relationship(
        "PatientPrescriptionMedicineLegacy",
        back_populates="prescription",
        cascade="all, delete",
    )
