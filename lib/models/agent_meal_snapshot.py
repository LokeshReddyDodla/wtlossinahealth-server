import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class AgentMealSnapshot(Base):
    __tablename__ = "agent_meal_snapshots"

    snapshot_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    meal_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_meals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    conversation_id = Column(Text, nullable=False, index=True)
    audience = Column(String(32), nullable=False)
    mode = Column(String(32), nullable=False)
    data_source_strategy = Column(String(64), nullable=False)
    features_json = Column(JSONB, nullable=False)
    evidence_json = Column(JSONB, nullable=False)
    output_json = Column(JSONB, nullable=False)
    pass1_json = Column(JSONB, nullable=False)
    model_meta_json = Column(JSONB, nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now().replace(tzinfo=None)
    )

    patient = relationship("Patient")
    meal = relationship("PatientMeal")
