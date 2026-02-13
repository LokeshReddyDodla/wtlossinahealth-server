import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
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
    calories = Column(Float)
    carbs = Column(Float)
    protein = Column(Float)
    fats = Column(Float)
    fiber = Column(Float)
    calcium = Column(Float)
    iron = Column(Float)
    zinc = Column(Float)
    magnesium = Column(Float)

    major_meal = Column(JSON, nullable=True)
    snack = Column(JSON, nullable=True)

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
