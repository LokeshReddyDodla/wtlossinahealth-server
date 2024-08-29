from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from lib.models import Base
import uuid
from datetime import datetime


class PatientVital(Base):
    __tablename__ = "patient_vitals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    a1c = Column(Float, nullable=True)
    creatinine = Column(Float, nullable=True)
    diastolic_bp = Column(Float, nullable=True)
    systolic_bp = Column(Float, nullable=True)
    heart_rate = Column(Float, nullable=True)
    ketones = Column(Float, nullable=True)
    respiratory_rate = Column(Float, nullable=True)
    spo2 = Column(Float, nullable=True)
    temperature = Column(Float, nullable=True)
    weight = Column(Float, nullable=True)
    test_time = Column(DateTime, nullable=False)
    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    source = Column(String, nullable=False)

    patient = relationship("Patient", back_populates="vitals")
