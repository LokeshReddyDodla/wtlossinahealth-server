import uuid
from datetime import datetime

from sqlalchemy import UUID, Column, DateTime, String, Text
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
    phone_number = Column(
        String, nullable=False, comment="Primary phone number of the facility"
    )
    emergency_phone_number = Column(
        String, nullable=True, comment="Emergency contact number"
    )
    email = Column(
        String, nullable=False, comment="Primary email address of the facility"
    )
    address = Column(
        Text,
        nullable=False,
        comment="Complete address of the  facility",
    )
    operating_hours = Column(
        Text, nullable=True, comment="Operating hours in JSON format"
    )
    facility_type = Column(
        String,
        nullable=False,
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

    subdomain = Column(
        String,
        unique=True,
        comment="Subdomain for the health facility",
    )
    custom_domain = Column(
        String,
        default="aihealth.clinic",
        comment="Custom domain for the health facility",
    )

    created_at = Column(DateTime, default=lambda: datetime.now().replace(tzinfo=None))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    # Relationships
    patients = relationship(
        "Patient",
        back_populates="health_facility",
        cascade="all, delete-orphan",
    )
    care_providers = relationship(
        "CareProvider",
        back_populates="health_facility",
        cascade="all, delete-orphan",
    )
    packages = relationship(
        "Package",
        back_populates="health_facility",
        cascade="all, delete-orphan",
    )
