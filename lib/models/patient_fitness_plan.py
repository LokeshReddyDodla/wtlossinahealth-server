import uuid
from datetime import datetime

from sqlalchemy import UUID, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientFitnessPlan(Base):
    __tablename__ = "patient_fitness_plans"

    fitness_plan_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    steps_goal = Column(Float)
    workout_plan = Column(String)
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    # Relationship to patient plan
    patient_plans = relationship("PatientPlan", back_populates="fitness_plan")
