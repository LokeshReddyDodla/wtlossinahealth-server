import uuid
from datetime import datetime

from sqlalchemy import UUID, Column, Date, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientPlan(Base):
    __tablename__ = "patient_plans"

    plan_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.patient_id"))
    diet_plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_diet_plans.diet_plan_id"),
        nullable=True,
    )
    fitness_plan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patient_fitness_plans.fitness_plan_id"),
        nullable=True,
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(
        Date, nullable=True
    )  # Can be null if it's an active plan
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    # Relationships to Diet and Fitness plans
    diet_plan = relationship("PatientDietPlan", back_populates="patient_plans")
    fitness_plan = relationship(
        "PatientFitnessPlan", back_populates="patient_plans"
    )

    # Relationship to Patient
    patient = relationship("Patient", back_populates="patient_plans")
