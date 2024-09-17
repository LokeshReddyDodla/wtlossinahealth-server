from sqlalchemy import (
    Column,
    UUID,
    DateTime,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from lib.models import Base
import uuid
from datetime import datetime


class PatientCareProvider(Base):
    __tablename__ = "patient_care_providers"

    patient_care_provider_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    care_provider_id = Column(
        UUID(as_uuid=True), ForeignKey("care_providers.care_provider_id")
    )
    assigned_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    roles = Column(
        JSON, nullable=True
    )  # Additional roles/permissions specific to this relationship

    # Relationships
    patient = relationship("Patient", back_populates="care_providers")
    care_provider = relationship(
        "CareProvider", back_populates="patient_relationships"
    )
