import uuid
from datetime import datetime

from sqlalchemy import UUID, Column, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship

from lib.models import Base
from lib.models.associations import package_care_provider_association


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

    care_providers = relationship(
        "CareProvider",
        secondary=package_care_provider_association,
        back_populates="packages",
    )
    patients = relationship(
        "Patient",
        back_populates="package",
    )
