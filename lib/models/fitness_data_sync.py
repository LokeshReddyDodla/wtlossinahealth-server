from datetime import datetime
import uuid
from sqlalchemy import UUID, Column, DateTime, ForeignKey
from lib.models import Base
from sqlalchemy.orm import relationship


class FitnessDataSync(Base):
    __tablename__ = "fitness_data_sync"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    last_sync_timestamp = Column(DateTime, nullable=True)
    patient = relationship("Patient", back_populates="fitness_syncs")
