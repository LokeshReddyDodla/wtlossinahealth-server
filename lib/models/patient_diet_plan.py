import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientDietPlan(Base):
    __tablename__ = "patient_diet_plans"

    diet_plan_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id"),
        nullable=False,
        index=True,
    )

    # Daily macro targets (top-level columns for SQL queries)
    calories = Column(Float, nullable=False)
    protein = Column(Float, nullable=False)
    carbs = Column(Float, nullable=False)
    fats = Column(Float, nullable=False)
    fiber = Column(Float, nullable=True)

    # Structured content: meals, restrictions, micronutrients, notes
    content = Column(JSONB, nullable=True)

    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    status = Column(String(20), default="ACTIVE", index=True)
    plan_reason = Column(String, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now().replace(tzinfo=None))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    # Relationships
    patient = relationship("Patient", back_populates="diet_plans")

    __table_args__ = (
        Index("ix_patient_diet_plan_status_date", "patient_id", "status", "start_date"),
    )
