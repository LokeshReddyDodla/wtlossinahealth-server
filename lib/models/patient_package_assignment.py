import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from enum import Enum
from sqlalchemy import Enum as SQLEnum

from lib.models import Base


class AssignmentStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PatientPackageAssignment(Base):
    __tablename__ = "patient_package_assignments"

    assignment_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    package_id = Column(
        UUID(as_uuid=True),
        ForeignKey("packages.package_id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(
        SQLEnum(AssignmentStatus),
        default=AssignmentStatus.ACTIVE,
        nullable=False,
        comment="Status of the assignment",
    )
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    # Relationships
    package = relationship("Package", back_populates="patient_assignments")
    patient = relationship("Patient", back_populates="package_assignments")

    __table_args__ = (
        CheckConstraint(
            "end_date >= start_date", name="ck_assignment_date_range"
        ),
        Index(
            "ix_patient_assignment_patient_dates",
            "patient_id",
            "start_date",
            "end_date",
        ),
    )
