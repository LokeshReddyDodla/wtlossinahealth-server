import uuid
from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class SleepCheckin(Base):
    __tablename__ = "sleep_checkins"
    __table_args__ = (
        UniqueConstraint("patient_id", "checkin_date", name="uq_sleep_checkin_patient_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    checkin_date = Column(Date, nullable=False)
    quality = Column(Integer, nullable=False)  # 1-5
    hours_slept = Column(Float, nullable=False)  # 0-24
    bed_time = Column(String, nullable=False)  # "HH:MM"
    wake_time = Column(String, nullable=False)  # "HH:MM"
    notes = Column(String, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    patient = relationship("Patient", back_populates="sleep_checkins")
