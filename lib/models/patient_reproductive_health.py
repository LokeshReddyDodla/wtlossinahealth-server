import uuid

from sqlalchemy import UUID, Boolean, Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientReproductiveHealth(Base):
    __tablename__ = "patient_reproductive_health"

    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), primary_key=True
    )
    is_pregnant = Column(Boolean, nullable=True)
    pregnancy_weeks = Column(Integer, nullable=True)
    menopause_status = Column(String(20), nullable=True)
    period_regularity = Column(String(20), nullable=True)
    uses_contraception = Column(Boolean, nullable=True)

    patient = relationship("Patient", back_populates="reproductive_health")
