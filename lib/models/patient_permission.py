from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from lib.models import Base


class PatientPermission(Base):
    __tablename__ = "patient_permissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    camera_permission = Column(Boolean, default=False)
    fitness_sync_permission = Column(Boolean, default=False)
    audio_permission = Column(Boolean, default=False)
    # Add other permissions as needed

    patient = relationship("Patient", back_populates="permissions")
