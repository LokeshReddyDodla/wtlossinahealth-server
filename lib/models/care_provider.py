import uuid
from datetime import datetime

from sqlalchemy import (JSON, UUID, Boolean, Column, DateTime, ForeignKey,
                        String)
from sqlalchemy.orm import relationship

from lib.models import Base


class CareProvider(Base):
    __tablename__ = "care_providers"

    care_provider_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    role = Column(
        String, nullable=False
    )  # e.g., Doctor, Nurse, Dietitian, etc.
    profile_picture = Column(String, nullable=True)
    phone_number = Column(String, unique=True, index=True)
    email = Column(String, nullable=False, unique=True)
    permissions = Column(
        JSON, nullable=True
    )  # Store permissions as JSON or use a separate permissions table
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )
    is_verified = Column(Boolean, default=False)

    profile_completion = Column(
        JSON,
        default={
            "basic": {"is_complete": False, "is_mandatory": True},
        },
    )

    # Relationships
    health_facility_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "health_facilities.health_facility_id", ondelete="SET NULL"
        ),
    )
    health_facility = relationship(
        "HealthFacility", back_populates="care_providers", passive_deletes=True
    )
    patient_relationships = relationship(
        "PatientCareProvider",
        back_populates="care_provider",
        cascade="all, delete-orphan",
    )

    user_devices = relationship(
        "UserDevice",
        back_populates="care_provider",
        cascade="all, delete-orphan",
    )
