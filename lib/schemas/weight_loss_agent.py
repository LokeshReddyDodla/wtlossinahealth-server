from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import UploadFile
from pydantic import BaseModel, Field




class InbodyMeasurementBase(BaseModel):
    measurement_type: str = Field(..., description="Type of measurement (e.g., weight, bmi, body_fat)")
    value: float
    unit: str = Field(..., description="Unit of measurement (e.g., kg, %, cm)")
    normal_min: Optional[float] = None
    normal_max: Optional[float] = None
    confidence_score: Optional[float] = None


class InbodyMeasurement(InbodyMeasurementBase):
    measurement_id: UUID
    report_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class HealthIndicatorBase(BaseModel):
    indicator_name: str = Field(..., description="Name of the health indicator")
    indicator_type: str = Field(..., description="Type of indicator (warning, critical, normal)")
    value: float
    unit: str
    is_abnormal: bool = False
    abnormality_level: Optional[str] = None
    normal_range_min: Optional[float] = None
    normal_range_max: Optional[float] = None
    analysis_explanation: Optional[str] = None
    recommendations: Optional[str] = None


class HealthIndicator(HealthIndicatorBase):
    indicator_id: UUID
    report_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class InbodyNormalizedFields(BaseModel):
    values: Dict[str, float] = Field(default_factory=dict)
    derived: Dict[str, float] = Field(default_factory=dict)
    parse_confidence: Dict[str, float] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    confirmation_needed: List[str] = Field(default_factory=list)


class InbodyReportBase(BaseModel):
    report_date: datetime
    ai_summary: Optional[str] = None
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    content_type: Optional[str] = None


class InbodyReportCreate(InbodyReportBase, InbodyNormalizedFields):
    pass


class InbodyReportUpload(BaseModel):
    report_date: datetime
    image_file: Optional[UploadFile] = None
    image_url: Optional[str] = None


class InbodyReport(InbodyReportBase, InbodyNormalizedFields):
    report_id: UUID
    enrollment_id: UUID
    extracted_at: datetime
    extraction_confidence: Optional[float] = None
    processed: bool = False
    created_at: datetime
    measurements_count: Optional[int] = 0
    abnormal_indicators_count: Optional[int] = 0
    measurements: List[InbodyMeasurement] = Field(default_factory=list)
    health_indicators: List[HealthIndicator] = Field(default_factory=list)

    class Config:
        from_attributes = True


class InbodyReportSummary(InbodyNormalizedFields):
    report_id: UUID
    report_date: datetime
    processed: bool
    extraction_confidence: Optional[float] = None
    abnormal_indicators_count: int = 0
    measurements_count: int = 0
    ai_summary: Optional[str] = None
    original_filename: Optional[str] = None
    measurements: List[InbodyMeasurement] = Field(default_factory=list)
    health_indicators: List[HealthIndicator] = Field(default_factory=list)





class DailyReportData(BaseModel):
    date: str
    meal_data: Optional[dict] = None
    fitness_data: Optional[dict] = None
    vitals_data: Optional[dict] = None


class WeightLossProgressReport(BaseModel):
    
    patient_id: UUID
    patient_name: str
    enrollment_date: datetime
    is_active: bool
    target_weight_kg: Optional[float] = None
    target_bmi: Optional[float] = None
    latest_inbody_report: Optional[InbodyReportSummary] = None
    daily_reports: List[DailyReportData] = Field(default_factory=list)
    program_goals: Optional[str] = None


class WeightLossAgentAnalysisRequest(BaseModel):
    patient_id: UUID
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    include_meal_analysis: bool = True
    include_fitness_analysis: bool = True
    include_vitals_analysis: bool = True


class WeightLossAgentAnalysisResponse(BaseModel):
    enrollment_id: UUID
    analysis_period: dict
    overall_health_score: Optional[float] = None
    key_insights: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    risk_factors: List[str] = Field(default_factory=list)
    progress_metrics: dict = Field(default_factory=dict)
    meal_analysis: Optional[dict] = None
    fitness_analysis: Optional[dict] = None
    vitals_analysis: Optional[dict] = None


class InbodyReportAnalysisResult(InbodyNormalizedFields):
    """Schema for the result returned from AI analysis of inbody report"""
    file_name: str
    processed_at: str
    ai_analysis: dict
    metadata: dict
    report_id: Optional[str] = None
    stored_at: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "file_name": "inbody_report.pdf",
                "processed_at": "2024-01-01T12:00:00",
                "ai_analysis": {
                    "summary": "Overall health score: 85/100...",
                    "confidence_score": 0.95,
                    "structured": True
                },
                "metadata": {
                    "content_type": "application/pdf",
                    "file_size": 2048576,
                    "enrollment_id": "123e4567-e89b-12d3-a456-426614174000",
                    "original_filename": "inbody_report.pdf",
                    "ready_for_storage": True,
                    "stored": False
                },
                "report_id": "123e4567-e89b-12d3-a456-426614174001",
                "stored_at": "2024-01-01T12:00:05"
            }
        }


class WeightLossEnrollmentBase(BaseModel):
    patient_id: UUID
    enrolled_by_care_provider_id: UUID
    program_goals: Optional[str] = None
    target_weight_kg: Optional[float] = None
    target_bmi: Optional[float] = None


class WeightLossEnrollmentCreate(WeightLossEnrollmentBase):
    """Payload to create a weight loss enrollment."""


class WeightLossEnrollmentUpdate(BaseModel):
    """Fields that can be updated on an enrollment."""
    program_goals: Optional[str] = None
    target_weight_kg: Optional[float] = None
    target_bmi: Optional[float] = None
    is_active: Optional[bool] = None


class WeightLossEnrollment(WeightLossEnrollmentBase):
    enrollment_id: UUID
    enrollment_date: datetime
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    """Schema for chat requests to the weight loss agent"""
    question: str = Field(..., description="User's question or message", min_length=1)
    conversation_id: Optional[str] = Field(None, description="Optional conversation ID for maintaining context")

    class Config:
        json_schema_extra = {
            "example": {
                "question": "How is my weight loss progress this week?",
                "conversation_id": "chat_123"
            }
        }
