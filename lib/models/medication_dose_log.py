"""Per-dose adherence log — tracks whether each specific medication was taken/missed/skipped."""

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
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from lib.models import Base


class MedicationDoseLog(Base):
    __tablename__ = "medication_dose_logs"

    dose_log_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    medication_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_medications.medication_id", ondelete="CASCADE"),
        nullable=False,
    )
    log_date = Column(Date, nullable=False)
    slot = Column(String, nullable=False)  # morning/afternoon/evening/night
    status = Column(String, nullable=False, default="taken")  # taken/missed/skipped
    taken_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    patient = relationship("Patient")
    medication = relationship("PatientMedication")

    __table_args__ = (
        UniqueConstraint(
            "patient_id", "medication_id", "log_date", "slot",
            name="uq_dose_log_patient_med_date_slot",
        ),
        Index("ix_dose_log_patient_date", "patient_id", "log_date"),
        Index("ix_dose_log_medication", "medication_id", "log_date"),
    )
