import uuid

from sqlalchemy import (ARRAY, UUID, Boolean, Column, ForeignKey, Integer,
                        String, Text)
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientCurrentMedication(Base):
    __tablename__ = "patient_current_medication"

    medication_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    has_medication = Column(Boolean)
    prescription_description = Column(Text, nullable=True)
    prescription_image_urls = Column(ARRAY(Text), nullable=True)
    patient = relationship("Patient", back_populates="current_medication")
