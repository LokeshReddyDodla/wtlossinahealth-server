from sqlalchemy import Column, Float, DateTime, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from lib.models import Base
import uuid
from datetime import datetime


class PatientSMBG(Base):
    __tablename__ = "patient_smbgs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    glucose_level = Column(Float, nullable=False)
    reading_time = Column(DateTime, nullable=False)
    source = Column(String, nullable=False)
    type = Column(String, nullable=False)  # pre_meal, post_meal, etc.
    notes = Column(String, nullable=True)
    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    patient = relationship("Patient", back_populates="smbg")
