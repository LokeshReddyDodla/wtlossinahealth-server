import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from lib.models import Base


class UserDevice(Base):
    __tablename__ = "user_devices"

    device_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True
    )
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    profile_type = Column(
        String, nullable=False
    )  # 'patient' or 'care_provider'

    last_updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )
    last_active_at = Column(DateTime, nullable=True)

    fcm_token = Column(String, nullable=True)
    device_type = Column(String, nullable=True)  # e.g., 'iOS', 'Android'
    platform_version = Column(String, nullable=True)
    device_model = Column(String, nullable=True)
    manufacturer = Column(String, nullable=True)
    device_name = Column(String, nullable=True)
    is_physical_device = Column(Boolean, nullable=True)
    app_name = Column(String, nullable=True)
    app_version = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_name = Column(String, nullable=True)
