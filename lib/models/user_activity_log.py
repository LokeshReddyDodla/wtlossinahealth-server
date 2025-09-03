from datetime import datetime
import uuid
from sqlalchemy import (
    UUID,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from lib.core.constants import ProfileTypeEnum
from lib.models import Base
from sqlalchemy.orm import relationship


class UserActivityLog(Base):
    __tablename__ = "user_activity_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, nullable=False, index=True)
    profile_type = Column(
        String, nullable=False
    )  # 'patient' or 'care_provider'

    device_id = Column(
        UUID,
        ForeignKey("user_devices.device_id", ondelete="CASCADE"),
        nullable=True,
    )
    api_endpoint = Column(
        String, nullable=True
    )  # e.g., "/meals", "/notifications"
    status_code = Column(Integer, nullable=True)  # response status
    method = Column(String, nullable=True)  # GET, POST, etc.
    ip_address = Column(String, nullable=True)

    active_at = Column(
        DateTime, default=datetime.utcnow, index=True
    )  # when the activity happened

    device = relationship("UserDevice", backref="activity_logs")

    __table_args__ = (
        Index(
            "ix_user_activity_logs_user_profile_time",
            "user_id",
            "profile_type",
            "active_at",
        ),
        Index(
            "ix_user_activity_logs_endpoint_time", "api_endpoint", "active_at"
        ),
    )
