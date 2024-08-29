import uuid
from sqlalchemy import UUID, Boolean, Column, ForeignKey, Integer, String
from lib.models import Base
from sqlalchemy.orm import relationship


class PatientFamilyDiabeticHistory(Base):
    __tablename__ = "patient_family_diabetic_histories"

    history_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    family_member = Column(String(50))
    patient = relationship("Patient", back_populates="family_diabetic_history")
