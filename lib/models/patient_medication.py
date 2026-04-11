"""Active medication model — what the patient is currently taking."""

import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
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


class PatientMedication(Base):
    __tablename__ = "patient_medications"

    medication_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    prescription_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "patient_prescriptions.prescription_id", ondelete="SET NULL"
        ),
        nullable=True,
    )

    # Medicine identity
    name = Column(String, nullable=False)
    brand_name = Column(String, nullable=True)
    strength = Column(String, nullable=True)
    formulation = Column(String, nullable=True)
    route = Column(String, nullable=True)

    # Dosing
    food_timing = Column(String, nullable=True)
    doses = Column(JSONB, nullable=False, default=list)

    # Context
    purpose = Column(String, nullable=True)
    instructions = Column(Text, nullable=True)

    # Scheduling (NULL = daily, all 7 days)
    schedule = Column(JSONB, nullable=True)

    # Duration
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)

    # Lifecycle
    status = Column(String, nullable=False, default="active")
    discontinued_at = Column(DateTime, nullable=True)
    discontinued_by = Column(UUID(as_uuid=True), nullable=True)

    # Dose adjustment lineage
    previous_medication_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_medications.medication_id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    patient = relationship("Patient", back_populates="medications")
    prescription = relationship(
        "PatientPrescription", back_populates="medications"
    )

    __table_args__ = (
        Index("ix_medication_patient_status", "patient_id", "status"),
        Index("ix_medication_patient_end", "patient_id", "end_date"),
    )
