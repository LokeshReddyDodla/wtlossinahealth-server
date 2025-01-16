import uuid
from datetime import datetime

from sqlalchemy import UUID, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientSleep(Base):
    __tablename__ = "patient_sleeps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    source_name = Column(String, nullable=False)
    source_platform = Column(String, nullable=False)
    type = Column(String, nullable=False)
    sleep_duration = Column(
        Float, nullable=False
    )  # Duration in minutes or hours
    sleep_start_time = Column(DateTime, nullable=False)
    sleep_end_time = Column(DateTime, nullable=False)
    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    patient = relationship("Patient", back_populates="sleep_entries")
