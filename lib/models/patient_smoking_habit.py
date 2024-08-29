import uuid
from sqlalchemy import UUID, Column, ForeignKey, Integer, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientSmokingHabit(Base):
    __tablename__ = "patient_smoking_habit"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    smoke_status = Column(String(20))
    years_of_smoking = Column(Integer, nullable=True)
    cigarettes_per_day = Column(Integer, nullable=True)
    quit_years_ago = Column(Integer, nullable=True)
    patient = relationship("Patient", back_populates="smoking_habit")
