from datetime import datetime
import uuid

from sqlalchemy import UUID, Column, DateTime, Float, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientSleep(Base):
    __tablename__ = "patient_sleep"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    source = Column(String, nullable=False)
    sleep_duration = Column(
        Float, nullable=False
    )  # Duration in minutes or hours
    sleep_start_time = Column(DateTime, nullable=False)
    sleep_end_time = Column(DateTime, nullable=False)
    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    patient = relationship("Patient", back_populates="sleep_data")
