import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class AgentMealFeatureCache(Base):
    __tablename__ = "agent_meal_feature_cache"

    cache_id = Column(
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
    window_start = Column(DateTime, nullable=False)
    window_end = Column(DateTime, nullable=False)
    feature_bundle_json = Column(JSONB, nullable=False)
    source_flags_json = Column(JSONB, nullable=False)
    generated_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now().replace(tzinfo=None)
    )
    expires_at = Column(DateTime, nullable=False, index=True)

    patient = relationship("Patient")
    meal = relationship("PatientMeal")
