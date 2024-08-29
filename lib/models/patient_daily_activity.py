import uuid
from sqlalchemy import UUID, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientDailyActivity(Base):
    __tablename__ = "patient_daily_activity"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    activity_level = Column(String(50))
    patient = relationship("Patient", back_populates="daily_activities")
