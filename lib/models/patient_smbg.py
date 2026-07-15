import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientSMBG(Base):
    __tablename__ = "patient_smbgs"
    __table_args__ = (
        UniqueConstraint(
            "patient_id", "reading_time", "source_name",
            name="uq_smbg_patient_time_source",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    glucose_level = Column(Float, nullable=False)
    reading_time = Column(DateTime, nullable=False)
    source_name = Column(String, nullable=False)
    source_platform = Column(String, nullable=False)
    type = Column(String, nullable=False)  # pre_meal, post_meal, etc.
    notes = Column(String, nullable=True)
    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    patient = relationship("Patient", back_populates="smbgs")
