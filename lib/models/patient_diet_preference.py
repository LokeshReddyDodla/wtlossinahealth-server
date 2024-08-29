import uuid
from sqlalchemy import UUID, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientDietPreference(Base):
    __tablename__ = "patient_diet_preferences"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    preference = Column(String(50))
    detail = Column(String(100), nullable=True)
    patient = relationship("Patient", back_populates="diet_preferences")
