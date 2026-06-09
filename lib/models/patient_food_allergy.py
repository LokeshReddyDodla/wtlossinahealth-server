import uuid

from sqlalchemy import UUID, Column, ForeignKey, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientFoodAllergy(Base):
    __tablename__ = "patient_food_allergies"

    allergy_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    allergy_name = Column(String(100))
    name = Column(String(50), nullable=True)
    name_other = Column(String(100), nullable=True)
    severity = Column(String(20), nullable=True)
    patient = relationship("Patient", back_populates="food_allergies")
