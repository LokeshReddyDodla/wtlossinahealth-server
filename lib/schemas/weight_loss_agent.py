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
    # Full section-separated OCR data
    sections: Optional[Dict[str, Any]] = None
    patient_info: Optional[Dict[str, Any]] = None
    inbody_score: Optional[int] = None

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


class MeasurementSummary(BaseModel):
    label: str
    value: Optional[float] = None
    unit: Optional[str] = None
    normal_min: Optional[float] = None
    normal_max: Optional[float] = None
    confidence_score: Optional[float] = None


# ---------------------------------------------------------------------------
# Section models — mirror each section/panel of the InBody printout
# ---------------------------------------------------------------------------

class PatientInfo(BaseModel):
    """Header row of the InBody printout."""
    patient_id_on_report: Optional[str] = None
    height_cm: Optional[float] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    test_date_time: Optional[str] = None


class CompositionEntry(BaseModel):
    """Single row inside Body Composition Analysis."""
    value: Optional[float] = None
    unit: Optional[str] = None
    normal_min: Optional[float] = None
    normal_max: Optional[float] = None


class BodyCompositionAnalysis(BaseModel):
    """Body Composition Analysis panel."""
    total_body_water: Optional[CompositionEntry] = None
    protein: Optional[CompositionEntry] = None
    minerals: Optional[CompositionEntry] = None
    body_fat_mass: Optional[CompositionEntry] = None
    soft_lean_mass: Optional[CompositionEntry] = None
    fat_free_mass: Optional[CompositionEntry] = None
    weight: Optional[CompositionEntry] = None


class MuscleFatEntry(BaseModel):
    """Row in Muscle-Fat Analysis with bar evaluation."""
    value: Optional[float] = None
    unit: Optional[str] = None
    bar_evaluation: Optional[str] = Field(None, description="Under / Normal / Over")


class MuscleFatAnalysis(BaseModel):
    """Muscle-Fat Analysis panel."""
    weight: Optional[MuscleFatEntry] = None
    smm: Optional[MuscleFatEntry] = None
    body_fat_mass: Optional[MuscleFatEntry] = None


class ObesityAnalysis(BaseModel):
    """Obesity Analysis panel (BMI & PBF with bar graphs)."""
    bmi: Optional[CompositionEntry] = None
    pbf: Optional[CompositionEntry] = None


class WeightControlEntry(BaseModel):
    value: Optional[float] = None
    unit: Optional[str] = None


class WeightControlSection(BaseModel):
    """Weight Control panel."""
    target_weight: Optional[WeightControlEntry] = None
    weight_control: Optional[WeightControlEntry] = None
    fat_control: Optional[WeightControlEntry] = None
    muscle_control: Optional[WeightControlEntry] = None


class NutritionEvaluation(BaseModel):
    """Nutrition Evaluation panel — each field is Normal / Deficient / Excessive."""
    protein: Optional[str] = None
    minerals: Optional[str] = None
    body_fat: Optional[str] = None


class ObesityEvaluation(BaseModel):
    """Obesity Evaluation panel — each field is Normal / Under / Slightly Over / Over."""
    bmi: Optional[str] = None
    pbf: Optional[str] = None


class SegmentalLeanEntry(BaseModel):
    """One segment in Segmental Lean Analysis."""
    value_kg: Optional[float] = None
    percentage: Optional[float] = Field(None, description="% of ideal for the segment")
    normal_range_pct: Optional[str] = Field(None, description="e.g. '80-120'")


class SegmentalLeanAnalysis(BaseModel):
    """Segmental Lean Analysis panel."""
    right_arm: Optional[SegmentalLeanEntry] = None
    left_arm: Optional[SegmentalLeanEntry] = None
    trunk: Optional[SegmentalLeanEntry] = None
    right_leg: Optional[SegmentalLeanEntry] = None
    left_leg: Optional[SegmentalLeanEntry] = None


class BodyBalanceEvaluation(BaseModel):
    """Body Balance Evaluation panel — each is Balanced / Slightly Unbalanced / Extremely Unbalanced."""
    upper: Optional[str] = None
    lower: Optional[str] = None
    upper_lower: Optional[str] = None


class ECWRatioPhaseAngle(BaseModel):
    """ECW Ratio-Phase Angle panel."""
    ecw_ratio: Optional[CompositionEntry] = None
    phase_angle: Optional[CompositionEntry] = None


class ResearchParameters(BaseModel):
    """Research Parameters panel."""
    intracellular_water: Optional[CompositionEntry] = None
    extracellular_water: Optional[CompositionEntry] = None
    basal_metabolic_rate: Optional[CompositionEntry] = None
    waist_hip_ratio: Optional[CompositionEntry] = None
    visceral_fat_level: Optional[CompositionEntry] = None
    obesity_degree: Optional[CompositionEntry] = None
    bone_mineral_content: Optional[CompositionEntry] = None
    body_cell_mass: Optional[CompositionEntry] = None


class BodyCompositionHistoryEntry(BaseModel):
    """One row in Body Composition History."""
    date: Optional[str] = None
    weight: Optional[float] = None
    smm: Optional[float] = None
    bfm: Optional[float] = None
    pbf: Optional[float] = None
    ecw_ratio: Optional[float] = None


class ImpedanceEntry(BaseModel):
    """Impedance per segment."""
    frequency_khz: Optional[float] = None
    right_arm: Optional[float] = None
    left_arm: Optional[float] = None
    trunk: Optional[float] = None
    right_leg: Optional[float] = None
    left_leg: Optional[float] = None


class SMI(BaseModel):
    """Skeletal Muscle Index."""
    value: Optional[float] = None
    unit: Optional[str] = "kg/m²"


class WholeBodyPhaseAngle(BaseModel):
    """Whole Body Phase Angle."""
    value: Optional[float] = None
    unit: Optional[str] = "°"


class InbodyReportSections(BaseModel):
    """All sections of the InBody printout grouped together."""
    patient_info: Optional[PatientInfo] = None
    inbody_score: Optional[int] = None
    body_composition_analysis: Optional[BodyCompositionAnalysis] = None
    muscle_fat_analysis: Optional[MuscleFatAnalysis] = None
    obesity_analysis: Optional[ObesityAnalysis] = None
    weight_control: Optional[WeightControlSection] = None
    nutrition_evaluation: Optional[NutritionEvaluation] = None
    obesity_evaluation: Optional[ObesityEvaluation] = None
    segmental_lean_analysis: Optional[SegmentalLeanAnalysis] = None
    body_balance_evaluation: Optional[BodyBalanceEvaluation] = None
    ecw_ratio_phase_angle: Optional[ECWRatioPhaseAngle] = None
    research_parameters: Optional[ResearchParameters] = None
    smi: Optional[SMI] = None
    whole_body_phase_angle: Optional[WholeBodyPhaseAngle] = None
    body_composition_history: List[BodyCompositionHistoryEntry] = Field(default_factory=list)
    impedance: List[ImpedanceEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Highlights & Detail (updated)
# ---------------------------------------------------------------------------

class InbodyReportHighlights(BaseModel):
    skeletal_muscle_mass: Optional[MeasurementSummary] = None
    body_fat_percentage: Optional[MeasurementSummary] = None
    visceral_fat_level: Optional[MeasurementSummary] = None
    basal_metabolic_rate: Optional[MeasurementSummary] = None
    segment_lean_analysis: List[MeasurementSummary] = Field(default_factory=list)
    # -- new highlights from full-OCR sections --
    inbody_score: Optional[int] = None
    weight_control: Optional[WeightControlSection] = None
    nutrition_evaluation: Optional[NutritionEvaluation] = None
    obesity_evaluation: Optional[ObesityEvaluation] = None
    body_balance_evaluation: Optional[BodyBalanceEvaluation] = None
    segmental_lean_detail: Optional[SegmentalLeanAnalysis] = None
    ecw_ratio: Optional[MeasurementSummary] = None
    phase_angle: Optional[MeasurementSummary] = None
    smi: Optional[MeasurementSummary] = None


class InbodyReportDetail(BaseModel):
    report: InbodyReport
    highlights: InbodyReportHighlights





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
