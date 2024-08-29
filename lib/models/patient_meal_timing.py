import uuid
from sqlalchemy import UUID, Column, ForeignKey, Integer, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientMealTiming(Base):
    __tablename__ = "patient_meal_timings"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    meal_type = Column(String(50))
    time = Column(String(50))
    patient = relationship("Patient", back_populates="meal_timings")
