from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import UploadFile
from pydantic import BaseModel, Field


class WeightLossEnrollmentBase(BaseModel):
    patient_id: UUID = Field(..., description="Unique identifier of the patient")
    program_goals: str = Field(..., description="Patient's weight loss goals and objectives", min_length=1, max_length=500)
    target_weight_kg: float = Field(..., description="Target weight in kilograms", gt=0, le=500)
    target_bmi: float = Field(..., description="Target BMI value", gt=0, le=50)


class WeightLossEnrollmentCreate(WeightLossEnrollmentBase):
    enrolled_by_care_provider_id: UUID = Field(..., description="Care provider who is enrolling the patient")

    class Config:
        json_schema_extra = {
            "example": {
                "patient_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "program_goals": "Lose 10kg in 3 months through healthy diet and exercise",
                "target_weight_kg": 70.5,
                "target_bmi": 24.0,
                "enrolled_by_care_provider_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
            }
        }


class WeightLossEnrollmentUpdate(BaseModel):
    is_active: Optional[bool] = Field(None, description="Whether the enrollment is active")
    program_goals: Optional[str] = Field(None, description="Updated weight loss goals", min_length=1, max_length=500)
    target_weight_kg: Optional[float] = Field(None, description="Updated target weight in kilograms", gt=0, le=500)
    target_bmi: Optional[float] = Field(None, description="Updated target BMI value", gt=0, le=50)


class WeightLossEnrollment(WeightLossEnrollmentBase):
    enrollment_id: UUID
    enrolled_by_care_provider_id: UUID
    enrollment_date: datetime
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


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


class InbodyReportBase(BaseModel):
    report_date: datetime
    ai_summary: Optional[str] = None
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    content_type: Optional[str] = None


class InbodyReportCreate(InbodyReportBase):
    pass


class InbodyReportUpload(BaseModel):
    report_date: datetime
    image_file: Optional[UploadFile] = None
    image_url: Optional[str] = None


class InbodyReport(InbodyReportBase):
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


class InbodyReportSummary(BaseModel):
    report_id: UUID
    report_date: datetime
    processed: bool
    extraction_confidence: Optional[float] = None
    abnormal_indicators_count: int = 0
    measurements_count: int = 0
    ai_summary: Optional[str] = None
    original_filename: Optional[str] = None





class DailyReportData(BaseModel):
    date: str
    meal_data: Optional[dict] = None
    fitness_data: Optional[dict] = None
    vitals_data: Optional[dict] = None


class WeightLossProgressReport(BaseModel):
    enrollment_id: UUID
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
    enrollment_id: UUID
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


class InbodyReportAnalysisResult(BaseModel):
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
