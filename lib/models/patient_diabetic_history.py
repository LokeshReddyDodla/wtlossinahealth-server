import uuid
from sqlalchemy import UUID, Boolean, Column, ForeignKey, Integer, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientDiabeticHistory(Base):
    __tablename__ = "patient_diabetic_history"

    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), primary_key=True
    )
    type_of_diabetes = Column(String(50), nullable=True)
    years_with_diabetes = Column(Integer, nullable=True)
    is_pregnant = Column(Boolean, nullable=True)
    pregnancy_weeks = Column(Integer, nullable=True)
    patient = relationship("Patient", back_populates="diabetic_history")
