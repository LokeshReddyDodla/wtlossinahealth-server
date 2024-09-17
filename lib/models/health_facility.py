from sqlalchemy import (
    Column,
    String,
    UUID,
    DateTime,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from lib.models import Base
import uuid
from datetime import datetime


class HealthFacility(Base):
    __tablename__ = "health_facilities"

    health_facility_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    name = Column(String, nullable=False)
    address = Column(Text, nullable=True)
    contact_info = Column(String, nullable=True)
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
