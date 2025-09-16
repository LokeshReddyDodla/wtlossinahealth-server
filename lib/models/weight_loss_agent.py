import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    UUID,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from lib.models import Base


class WeightLossAgentEnrollment(Base):
    """Tracks patient enrollment in the weight loss program"""

    __tablename__ = "weight_loss_agent_enrollments"

    enrollment_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    enrolled_by_care_provider_id = Column(
        UUID(as_uuid=True),
        ForeignKey("care_providers.care_provider_id", ondelete="SET NULL"),
        nullable=False,
    )
    enrollment_date = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    program_goals = Column(Text, nullable=True)  # JSON string for program goals
    target_weight_kg = Column(Float, nullable=True)
    target_bmi = Column(Float, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
        nullable=True,
    )

    # Relationships
    patient = relationship("Patient", back_populates="weight_loss_enrollment")
    enrolled_by = relationship("CareProvider", back_populates="weight_loss_enrollments")
    inbody_reports = relationship(
        "InbodyReport",
        back_populates="enrollment",
        cascade="all, delete-orphan",
        order_by="InbodyReport.report_date.desc()",
    )


class InbodyReport(Base):
    """Stores inbody report data extracted from uploaded images"""

    __tablename__ = "inbody_reports"

    report_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    enrollment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("weight_loss_agent_enrollments.enrollment_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ai_summary = Column(Text, nullable=True)  # AI-generated analysis summary
    original_filename = Column(String(255), nullable=True)  # Original uploaded file name
    file_size = Column(Integer, nullable=True)  # Size of uploaded file in bytes
    content_type = Column(String(100), nullable=True)  # MIME type of uploaded file
    report_date = Column(DateTime, nullable=False)
    extracted_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )
    extraction_confidence = Column(Float, nullable=True)  # AI confidence score
    processed = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )

    # Relationships
    enrollment = relationship("WeightLossAgentEnrollment", back_populates="inbody_reports")
    measurements = relationship(
        "InbodyMeasurement",
        back_populates="report",
        cascade="all, delete-orphan",
    )
    health_indicators = relationship(
        "HealthIndicator",
        back_populates="report",
        cascade="all, delete-orphan",
    )


class InbodyMeasurement(Base):
    """Individual measurements extracted from inbody reports"""

    __tablename__ = "inbody_measurements"

    measurement_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    report_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inbody_reports.report_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    measurement_type = Column(String(100), nullable=False)  # e.g., "weight", "bmi", "body_fat", etc.
    value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)  # e.g., "kg", "%", "cm", etc.
    normal_min = Column(Float, nullable=True)  # Normal range minimum
    normal_max = Column(Float, nullable=True)  # Normal range maximum
    confidence_score = Column(Float, nullable=True)  # Extraction confidence
    created_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )

    # Relationships
    report = relationship("InbodyReport", back_populates="measurements")


class HealthIndicator(Base):
    """Analyzed health indicators with abnormality flags"""

    __tablename__ = "health_indicators"

    indicator_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    report_id = Column(
        UUID(as_uuid=True),
        ForeignKey("inbody_reports.report_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    indicator_name = Column(String(100), nullable=False)  # e.g., "obesity", "muscle_mass", etc.
    indicator_type = Column(String(50), nullable=False)  # e.g., "warning", "critical", "normal"
    value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    is_abnormal = Column(Boolean, default=False, nullable=False)
    abnormality_level = Column(String(20), nullable=True)  # "low", "high", "critical"
    normal_range_min = Column(Float, nullable=True)
    normal_range_max = Column(Float, nullable=True)
    analysis_explanation = Column(Text, nullable=True)  # AI-generated explanation
    recommendations = Column(Text, nullable=True)  # AI-generated recommendations
    created_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )

    # Relationships
    report = relationship("InbodyReport", back_populates="health_indicators")


class NormalRange(Base):
    """Normal ranges for different health measurements"""

    __tablename__ = "normal_ranges"

    range_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        index=True,
    )
    indicator_name = Column(String(100), nullable=False)  # e.g., "bmi", "body_fat", etc.
    gender = Column(String(10), nullable=True)  # "male", "female", or None for both
    age_group_min = Column(Integer, nullable=True)  # Minimum age in years
    age_group_max = Column(Integer, nullable=True)  # Maximum age in years
    min_value = Column(Float, nullable=False)
    max_value = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        nullable=False,
    )

    def __repr__(self):
        return f"<NormalRange(indicator_name='{self.indicator_name}', gender='{self.gender}', min={self.min_value}, max={self.max_value})>"

