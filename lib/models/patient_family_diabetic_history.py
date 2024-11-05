import uuid

from sqlalchemy import UUID, Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientFamilyDiabeticHistory(Base):
    __tablename__ = "patient_family_diabetic_histories"

    history_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    family_member = Column(String(50))
    years_with_diabetes = Column(Integer, nullable=True)

    
    patient = relationship("Patient", back_populates="family_diabetic_histories")
