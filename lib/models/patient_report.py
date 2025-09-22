import uuid
from datetime import datetime
from sqlalchemy import (
    JSON,
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from lib.models import Base


class ReportTypeEnum(str, Enum):
    pdf = "pdf"
    docx = "docx"
    csv = "csv"
    image = "image"
    other = "other"


class PatientReport(Base):
    __tablename__ = "patient_reports"

    report_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        unique=True,
    )

    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        index=True,
    )

    report_type = Column(String, nullable=False)

    # Metadata
    file_name = Column(String, nullable=False)
    file_type = Column(String, nullable=False)
    uploaded_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    uploaded_by_id = Column(
        String, nullable=True
    )  # patient_id or care_provider_id
    uploaded_by_type = Column(
        String, nullable=True
    )  # "patient" or "care_provider"

    # Storage / access
    file_url = Column(Text, nullable=False)
    content_extracted = Column(Text, nullable=True)

    # Relationships
    patient = relationship("Patient", back_populates="reports")
