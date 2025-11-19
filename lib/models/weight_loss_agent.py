import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import relationship

from lib.models import Base


class WeightLossAgentEnrollment(Base):
    """Tracks patient enrollment in the weight loss program"""

    __tablename__ = "weight_loss_agent_enrollments"

    enrollment_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enrolled_by_care_provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("care_providers.care_provider_id", ondelete="SET NULL"),
        nullable=False,
    )
    enrollment_date = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    program_goals = Column(Text, nullable=True)  # JSON string for program goals
    target_weight_kg = Column(Float, nullable=True)
    target_bmi = Column(Float, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
        nullable=True,
    )

    # Relationships
    patient = relationship("Patient", back_populates="weight_loss_enrollment")
    enrolled_by = relationship("CareProvider", back_populates="weight_loss_enrollments")
    # Inbody reports and related artifacts now live in MongoDB, so we no longer
    # maintain SQLAlchemy relationships for those entities.
