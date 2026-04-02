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
    Boolean,
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
    calories = Column(Float, nullable=True)
    protein = Column(Float, nullable=True)
    carbs = Column(Float, nullable=True)
    fats = Column(Float, nullable=True)
    fiber = Column(Float, nullable=True)

    # Structured content: meals, restrictions, micronutrients, notes
    content = Column(JSONB, nullable=True)

    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    is_default = Column(Boolean, default=False, index=True)
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
        Index(
            "ix_patient_diet_plan_default",
            "patient_id",
            unique=True,
            postgresql_where="is_default = true",
        ),
        Index("ix_patient_diet_plan_status_date", "patient_id", "status", "start_date"),
    )
