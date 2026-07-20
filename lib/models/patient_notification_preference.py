import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    String,
    UniqueConstraint,
)

from lib.models import Base


class PatientNotificationPreference(Base):
    """Per-category mute switch. Absence of a row = enabled (opt-out model):
    a patient only appears here for categories they've explicitly turned off.
    CRITICAL-tier categories ignore this table entirely — they are unmutable
    by policy, enforced in the broker, not here.
    """

    __tablename__ = "patient_notification_preferences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    category = Column(String(40), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=lambda: datetime.now().replace(tzinfo=None))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    __table_args__ = (
        UniqueConstraint("patient_id", "category", name="uq_patient_notif_pref"),
    )
