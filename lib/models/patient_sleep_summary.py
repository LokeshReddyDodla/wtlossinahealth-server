import uuid
from sqlalchemy import UUID, Boolean, Column, Float, ForeignKey, String, Time
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientSleepSummary(Base):
    __tablename__ = "patient_sleep_summary"

    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), primary_key=True
    )
    sleep_quality = Column(String(50))
    wake_up_fresh = Column(Boolean)
    drowsy_day = Column(Boolean)
    average_sleep_duration = Column(Float, nullable=True)
    wake_up_time = Column(Time, nullable=True)
    bed_time = Column(Time, nullable=True)
    patient = relationship("Patient", back_populates="sleep_summary")
