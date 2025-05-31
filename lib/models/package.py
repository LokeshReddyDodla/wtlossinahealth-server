import random
import string
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    UUID,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy import Enum as SQLEnum

from lib.models import Base
from lib.models.associations import package_care_provider_association
from enum import Enum


class PackageStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DRAFT = "draft"
    DEPRECATED = "deprecated"


class Package(Base):
    __tablename__ = "packages"

    package_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    name = Column(String, nullable=False, comment="Name of the package")
    code = Column(
        String(6),
        nullable=False,
        unique=True,
        comment="Unique 6-digit uppercase code for the package",
    )
    description = Column(
        String,
        nullable=True,
        comment="Short description of what this package includes",
    )
    duration_days = Column(
        Integer,
        nullable=False,
        comment="Total duration of the package in days",
    )
    price = Column(
        Integer,
        nullable=True,
        comment="Optional price in smallest currency unit (e.g., cents)",
    )
    status = Column(
        SQLEnum(PackageStatus),
        default=PackageStatus.ACTIVE,
        nullable=False,
        comment="Current status of the package (active, archived, draft, etc.)",
    )
    features = Column(
        JSON,
        nullable=True,
        comment="JSON defining feature flags or module availability for this package",
    )
    package_type = Column(
        String,
        nullable=True,
        comment="E.g., 'Basic', 'Premium', 'Trial', etc.",
    )
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    health_facility_id = Column(
        UUID(as_uuid=True), ForeignKey("health_facilities.health_facility_id")
    )
    health_facility = relationship("HealthFacility", back_populates="packages")

    # Link to CareProvider who created this package
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("care_providers.care_provider_id", ondelete="SET NULL"),
        nullable=True,
        comment="Care Provider who created the package",
    )
    created_by = relationship(
        "CareProvider",
        back_populates="created_packages",
    )  # Care Provider who created the package

    care_providers = relationship(
        "CareProvider",
        secondary=package_care_provider_association,
        back_populates="packages",
    )

    patient_assignments = relationship(
        "PatientPackageAssignment",
        back_populates="package",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "name",
            "health_facility_id",
            name="uq_package_name_per_health_facility",
        ),
    )

    @property
    def active_patients(self):
        today = date.today()
        return [
            assignment.patient
            for assignment in self.patient_assignments
            if assignment.status == "active"
            and assignment.start_date <= today <= assignment.end_date
        ]
