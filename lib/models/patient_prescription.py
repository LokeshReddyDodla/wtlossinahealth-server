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

    # Core Medicine Info
    brand_name = Column(String, nullable=True)  # e.g., "Glycomet"
    generic_name = Column(String, nullable=True)  # e.g., "Metformin"
    formulation = Column(
        String, nullable=True
    )  # e.g., "Tablet", "Syrup", "Injection"
    strength = Column(String, nullable=True)  # e.g., "500 mg", "5 mg/5 ml"

    # Prescription Details
    frequency = Column(String, nullable=True)  # e.g., "1-0-1", "SOS"
    duration = Column(String, nullable=True)  # e.g., "5 Days", "2 Weeks"
    before_after_food = Column(
        String, nullable=True
    )  # e.g., "Before food", "After food"
    route = Column(String, nullable=True)  # e.g., "Oral", "IV", "Topical"
    instructions = Column(
        Text, nullable=True
    )  # Any extra freeform instructions

    # Optional Clinical Context
    purpose = Column(Text, nullable=True)
    possible_side_effects = Column(JSONB, nullable=True)

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
