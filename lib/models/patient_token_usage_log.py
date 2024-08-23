import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from lib.models import Base


class PatientTokenUsageLog(Base):
    __tablename__ = "patient_token_usage_log"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    api_type = Column(String, nullable=False)  # e.g., "OpenAI"
    api_endpoint = Column(
        String, nullable=False
    )  # e.g., "/get_nutritional_info"
    tokens_used = Column(Integer, nullable=False)
    model_used = Column(String, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
    patient = relationship("Patient", back_populates="token_usage_logs")
