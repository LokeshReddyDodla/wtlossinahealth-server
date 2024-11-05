import uuid

from sqlalchemy import UUID, Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientMedicalHistory(Base):
    __tablename__ = "patient_medical_histories"

    history_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    condition = Column(String(100))
    duration_years = Column(Integer)
    details = Column(Text, nullable=True)
    patient = relationship("Patient", back_populates="medical_histories")
