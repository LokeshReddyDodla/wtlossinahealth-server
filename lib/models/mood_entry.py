import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class MoodEntry(Base):
    __tablename__ = "mood_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    level = Column(Integer, nullable=False)  # 1-5
    emoji = Column(String, nullable=False)  # very_bad|bad|neutral|good|great
    tags = Column(ARRAY(String), default=[])
    notes = Column(String, nullable=True)
    recorded_at = Column(DateTime, nullable=False)  # when mood was felt
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    patient = relationship("Patient", back_populates="mood_entries")

    __table_args__ = (
        Index("ix_mood_entries_patient_recorded", "patient_id", "recorded_at"),
    )
