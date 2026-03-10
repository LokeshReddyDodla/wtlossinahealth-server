from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


AudienceLiteral = Literal["patient", "care_provider"]
ModeLiteral = Literal["auto", "pre_meal", "post_meal"]
VerdictLiteral = Literal["under", "within", "over"]


class MealAgentRequest(BaseModel):
    patient_id: UUID
    audience: AudienceLiteral
    message: str = Field(min_length=1)
    meal_id: Optional[UUID] = None
    conversation_id: Optional[str] = None
    mode: ModeLiteral = "auto"


class MealAgentScores(BaseModel):
    overall: float
    glucose_impact: float
    adherence: float


class MealAgentVerdicts(BaseModel):
    calories: VerdictLiteral
    carbs: VerdictLiteral
    protein: VerdictLiteral
    fat: VerdictLiteral
    fiber: VerdictLiteral


class HistoricalComparison(BaseModel):
    window_days: int = 14
    cohort_type: str = "same_meal_type_time_bucket"
    cohort_size: int = 0
    deltas_pct: Dict[str, float] = Field(default_factory=dict)
    trend_note: str = ""


class GlycemicResponse(BaseModel):
    baseline_mgdl: Optional[float] = None
    peak_mgdl: Optional[float] = None
    delta_mgdl: Optional[float] = None
    time_to_peak_min: Optional[int] = None
    return_to_baseline_2h: Optional[bool] = None


class DataUsedFlags(BaseModel):
    reports: bool = False
    raw_fallback_used: bool = False
    cgm: bool = False
    smbg: bool = False
    sleep: bool = False
    fitness: bool = False
    vitals: bool = False
    qdrant: bool = False


class CareProviderView(BaseModel):
    evidence_points: List[Dict[str, Any]] = Field(default_factory=list)
    metrics_table: Dict[str, Any] = Field(default_factory=dict)


class MealAgentResponseData(BaseModel):
    conversation_id: str
    snapshot_id: UUID
    summary_text: str
    scores: MealAgentScores
    verdicts: MealAgentVerdicts
    historical_comparison: HistoricalComparison
    glycemic_response: Optional[GlycemicResponse] = None
    next_best_actions: List[str] = Field(default_factory=list, max_length=3)
    data_used: DataUsedFlags
    warnings: List[str] = Field(default_factory=list)
    confidence: float
    care_provider_view: Optional[CareProviderView] = None


class SnapshotReadResponse(BaseModel):
    snapshot_id: UUID
    patient_id: UUID
    meal_id: Optional[UUID] = None
    conversation_id: str
    audience: AudienceLiteral
    mode: str
    data_source_strategy: str
    features_json: Dict[str, Any]
    evidence_json: Dict[str, Any]
    output_json: Dict[str, Any]
    pass1_json: Dict[str, Any]
    model_meta_json: Dict[str, Any]
    created_at: datetime


class MealAgentMessage(BaseModel):
    id: str
    conversation_id: str
    patient_id: str
    meal_id: Optional[str] = None
    audience: AudienceLiteral
    role: Literal["user", "assistant", "system"]
    content: str
    message_type: Literal["text", "json_ref"] = "text"
    snapshot_id: Optional[str] = None
    created_at: datetime
