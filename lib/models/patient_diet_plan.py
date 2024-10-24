import uuid
from datetime import datetime

from sqlalchemy import UUID, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientDietPlan(Base):
    __tablename__ = "patient_diet_plans"

    diet_plan_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    total_calories = Column(Float)
    carbs = Column(Float)
    protein = Column(Float)
    fats = Column(Float)
    fiber = Column(Float)
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    # Relationship to patient plan
    patient_plans = relationship("PatientPlan", back_populates="diet_plan")
