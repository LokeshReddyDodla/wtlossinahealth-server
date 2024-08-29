import uuid
from sqlalchemy import JSON, UUID, Boolean, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientAlcoholConsumption(Base):
    __tablename__ = "patient_alcohol_consumption"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    consume_alcohol = Column(Boolean)
    frequency = Column(String(50), nullable=True)
    quantity = Column(String(50), nullable=True)
    type_of_alcohol = Column(JSON, nullable=True)
    patient = relationship("Patient", back_populates="alcohol_consumption")
