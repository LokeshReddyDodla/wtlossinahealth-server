import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from lib.models import Base


class PatientDataExport(Base):
    __tablename__ = "patient_data_exports"

    export_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    requester_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    requester_role = Column(String(32), nullable=False)

    status = Column(String(32), nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)

    s3_object_key = Column(Text, nullable=True)
    checksum = Column(String(128), nullable=True)
    manifest = Column(JSONB, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )
    completed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True, index=True)
    last_downloaded_at = Column(DateTime, nullable=True)
