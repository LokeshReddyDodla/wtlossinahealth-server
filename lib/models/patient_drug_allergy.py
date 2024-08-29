import uuid
from sqlalchemy import UUID, Column, ForeignKey, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientDrugAllergy(Base):
    __tablename__ = "patient_drug_allergies"

    allergy_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    allergy_name = Column(String(100))
    patient = relationship("Patient", back_populates="drug_allergies")
