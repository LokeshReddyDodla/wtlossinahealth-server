import uuid

from sqlalchemy import JSON, UUID, Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientAlcoholConsumption(Base):
    __tablename__ = "patient_alcohol_consumption"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    consume_alcohol = Column(Boolean)
    status = Column(String(20), nullable=True)
    frequency = Column(String(50), nullable=True)
    quantity = Column(String(50), nullable=True)
    drinks_per_session = Column(Integer, nullable=True)
    type_of_alcohol = Column(JSON, nullable=True)
    quit_years_ago = Column(Integer, nullable=True)
    patient = relationship("Patient", back_populates="alcohol_consumption")
