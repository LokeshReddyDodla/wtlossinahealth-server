import uuid

from sqlalchemy import ARRAY, UUID, Boolean, Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientSmokingHabit(Base):
    __tablename__ = "patient_smoking_habit"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    smoke_status = Column(Boolean)
    status = Column(String(20), nullable=True)
    smoke_type = Column(ARRAY(String), nullable=True)
    years_of_smoking = Column(Float, nullable=True)
    cigarettes_per_day = Column(Integer, nullable=True)
    quit_years_ago = Column(Integer, nullable=True)
    patient = relationship("Patient", back_populates="smoking_habit")
