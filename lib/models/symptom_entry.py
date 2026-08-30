import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class SymptomEntry(Base):
    __tablename__ = "symptom_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True), ForeignKey("patients.patient_id"), nullable=False
    )
    recorded_at = Column(DateTime, nullable=False)  # when symptoms were felt
    notes = Column(String, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )

    patient = relationship("Patient", back_populates="symptom_entries")
    items = relationship(
        "SymptomEntryItem", back_populates="entry", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_symptom_entries_patient_recorded", "patient_id", "recorded_at"),
    )


class SymptomEntryItem(Base):
    __tablename__ = "symptom_entry_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symptom_entry_id = Column(
        UUID(as_uuid=True),
        ForeignKey("symptom_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symptom_name = Column(String, nullable=False)
    severity = Column(Integer, nullable=False)  # 1-5
    custom_label = Column(String, nullable=True)  # only when symptom_name='other'

    entry = relationship("SymptomEntry", back_populates="items")
