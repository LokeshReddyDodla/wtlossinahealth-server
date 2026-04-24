import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from lib.models import Base


class PatientNotification(Base):
    __tablename__ = "patient_notifications"
    __table_args__ = (
        Index(
            "ix_patient_notifications_patient_created",
            "patient_id",
            "created_at",
        ),
        Index(
            "ix_patient_notifications_patient_unread",
            "patient_id",
            postgresql_where="read_at IS NULL",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )

    category = Column(String(32), nullable=False)
    title = Column(String(200), nullable=False)
    body = Column(Text, nullable=False)
    severity = Column(String(16), nullable=True)
    deeplink = Column(String(500), nullable=True)
    data = Column(JSONB, nullable=False, default=dict)

    read_at = Column(DateTime, nullable=True)
    dismissed_at = Column(DateTime, nullable=True)
    # Python-side default ensures a value is always sent, even if the DB
    # column's server_default is missing on a given environment.
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now().replace(tzinfo=None),
        server_default=func.now(),
    )
