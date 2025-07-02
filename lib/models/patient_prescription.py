from datetime import datetime
import uuid
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
from lib.models import Base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB


class PatientPrescriptionMedicine(Base):
    __tablename__ = "patient_prescription_medicines"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    prescription_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "patient_prescriptions.prescription_id", ondelete="CASCADE"
        ),
        nullable=False,
    )

    name = Column(String, nullable=False)
    dosage = Column(String, nullable=False)
    frequency = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    purpose = Column(Text, nullable=True)
    possible_side_effects = Column(JSONB, nullable=True)
    instructions = Column(Text, nullable=True)
    explanation = Column(Text, nullable=False)

    prescription = relationship(
        "PatientPrescription", back_populates="medicines"
    )


class PatientPrescription(Base):
    __tablename__ = "patient_prescriptions"

    prescription_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )

    patient = relationship("Patient", back_populates="prescriptions")

    doctor_name = Column(String, nullable=False)
    prescription_date = Column(String, nullable=False)
    prescription_file_url = Column(Text, nullable=False)

    analyzed = Column(Boolean, default=True, nullable=False)
    source = Column(
        String, default="ai", nullable=False
    )  # e.g., "ai", "manual", "imported"

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
        "PatientPrescriptionMedicine",
        back_populates="prescription",
        cascade="all, delete",
    )
