import uuid
from datetime import datetime

from sqlalchemy import (JSON, UUID, Boolean, Column, DateTime, ForeignKey,
                        String)
from sqlalchemy.orm import relationship

from lib.models import Base
from lib.models.associations import (package_care_provider_association,
                                     patient_care_provider_association)


class CareProvider(Base):
    __tablename__ = "care_providers"

    care_provider_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    code = Column(
        String(6),
        nullable=False,
        unique=True,
        comment="Unique 6-digit uppercase code for the package",
    )

    # Personal Info
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    profile_picture = Column(String, nullable=True)
    phone_number = Column(String, unique=True, index=True)
    email = Column(String, nullable=False, unique=True)
    role = Column(String, nullable=False)  # e.g., Doctor, Nurse, Dietitian, etc.
    hashed_password = Column(String, nullable=True)

    # Clinic Info
    clinic_name = Column(String, nullable=False)
    clinic_phone_number = Column(String, nullable=False)
    clinic_address = Column(String, nullable=False)
    clinic_website_url = Column(String, nullable=True)

    # Medical Info
    medical_council_number = Column(String, nullable=False, unique=True)
    certificates = Column(JSON, nullable=True)

    # System Fields
    permissions = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now().replace(tzinfo=None))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )
    is_verified = Column(Boolean, default=False)

    profile_completion = Column(
        JSON,
        default={
            "personal_info": {"is_complete": False, "is_mandatory": True},
            "clinic_info": {"is_complete": False, "is_mandatory": True},
            "medical_info": {"is_complete": False, "is_mandatory": True},
        },
    )

    # Foreign Keys
    health_facility_id = Column(
        UUID(as_uuid=True),
        ForeignKey("health_facilities.health_facility_id", ondelete="SET NULL"),
    )
    health_facility = relationship(
        "HealthFacility", back_populates="care_providers", passive_deletes=True
    )
    patients = relationship(
        "Patient",
        secondary=patient_care_provider_association,
        back_populates="care_providers",
    )

    packages = relationship(
        "Package",
        secondary=package_care_provider_association,
        back_populates="care_providers",
    )

    created_packages = relationship(
        "Package",
        back_populates="created_by",
        cascade="all, delete-orphan",
    )  # Packages created by this care provider

    user_devices = relationship(
        "UserDevice",
        back_populates="care_provider",
        cascade="all, delete-orphan",
    )
