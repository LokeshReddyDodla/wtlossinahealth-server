"""Patient-level InBody report — file pointer, lifecycle status, extracted
analysis and insight.

The extracted analysis is a fixed per-scan document, so it lives here as
JSON rather than in a separate document store.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Column,
    Date,
    DateTime,
    Index,
    ForeignKey,
    String,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from lib.models import Base


class PatientInbodyReport(Base):
    __tablename__ = "patient_inbody_reports"

    report_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_url = Column(String, nullable=False)
    original_filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    # Date printed on the scan, distinct from upload time; source of ordering
    # for trends.
    report_date = Column(Date, nullable=False)
    status = Column(String, nullable=False, default="uploaded")
    # 'care_provider' | 'patient' — audit of who uploaded, not authorization.
    uploaded_by_role = Column(String, nullable=True)
    uploaded_by_id = Column(UUID(as_uuid=True), nullable=True)
    error = Column(String, nullable=True)
    # InbodyExtraction dump; set when extraction succeeds.
    analysis = Column(JSON, nullable=True)

    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    patient = relationship("Patient")

    __table_args__ = (
        Index("ix_inbody_patient_report_date", "patient_id", "report_date"),
    )
