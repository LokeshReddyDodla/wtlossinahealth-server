import uuid
from datetime import datetime

from sqlalchemy import (Column, DateTime, Enum, ForeignKey, Integer, Numeric,
                        String)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from lib.core.constants import ProfileTypeEnum
from lib.models import Base


class TokenUsageLog(Base):
    __tablename__ = "token_usage_logs"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )
    user_id = Column(UUID(as_uuid=True), nullable=False)
    user_type = Column(Enum(ProfileTypeEnum), nullable=False)
    api_endpoint = Column(
        String, nullable=False
    )  # e.g., "/v1/meals/preview"
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    cached_input_tokens = Column(Integer, nullable=True)
    cost = Column(Numeric(10, 4), nullable=False)
    model_used = Column(String, nullable=False)
    model_provider = Column(String, nullable=False)  # e.g., "openai", "gemini"
    created_at = Column(
        DateTime, default=lambda: datetime.now().replace(tzinfo=None)
    )
