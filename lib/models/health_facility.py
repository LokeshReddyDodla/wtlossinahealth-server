import uuid
from datetime import datetime

from sqlalchemy import UUID, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from lib.models import Base


class HealthFacility(Base):
    __tablename__ = "health_facilities"

    health_facility_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    name = Column(
        String,
        nullable=False,
        comment="Name of the health facility (e.g., XYZ Hospital)",
    )
    logo_url = Column(
        String, nullable=True, comment="URL of the facility's logo (optional)"
    )
    operating_hours = Column(
        Text, nullable=True, comment="Operating hours in JSON format"
    )
    facility_type = Column(
        String,
        nullable=True,
        comment="Type of facility (e.g., hospital, clinic, diagnostic center)",
    )
    website_url = Column(
        String, nullable=True, comment="Website of the health facility"
    )
    specialties = Column(
        Text,
        nullable=True,
        comment="List of specialties offered in JSON format (e.g., cardiology, dermatology)",
    )
    latitude = Column(
        String, nullable=True, comment="Latitude of the facility location"
    )
    longitude = Column(
        String, nullable=True, comment="Longitude of the facility location"
    )
    parent_organization = Column(
        String,
        nullable=True,
        comment="Parent organization or group name (if applicable)",
    )
    emergency_contact = Column(
        String, nullable=True, comment="Emergency contact number"
    )
    address = Column(
        Text,
        nullable=True,
        comment="Complete address of the  facility",
    )
    contact_info = Column(
        String,
        nullable=True,
        comment="General contact information such as phone or email",
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
    care_providers = relationship(
        "CareProvider",
        back_populates="health_facility",
        cascade="all, delete-orphan",
    )
    patients = relationship(
        "Patient",
        back_populates="health_facility",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
