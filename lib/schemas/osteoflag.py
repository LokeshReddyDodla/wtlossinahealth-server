from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class OsteoFlagRiskFactors(BaseModel):
    postmenopausal: Optional[bool] = None
    long_term_glucocorticoids: Optional[bool] = None
    prior_low_trauma_fracture: Optional[bool] = None
    rheumatoid_arthritis: Optional[bool] = None
    low_body_weight: Optional[bool] = None
    smoking: Optional[bool] = None
    parental_hip_fracture: Optional[bool] = None
    alcohol_high: Optional[bool] = None
    secondary_osteoporosis: Optional[bool] = None


class OsteoFlagBmd(BaseModel):
    available: bool
    femoral_neck_t_score: Optional[float] = None
    extraction_confidence_0_1: Optional[float] = Field(
        None, ge=0, le=1
    )


class OsteoFlagInput(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    
    patient_age_years: Optional[int] = Field(None, ge=0)
    sex: Literal["female", "male", "other", "unknown"]
    cxr_view: Literal["PA", "AP", "lateral", "unknown"]
    model_name: str
    model_risk_score_0_1: float = Field(..., ge=0, le=1)
    model_uncertainty_0_1: Optional[float] = Field(None, ge=0, le=1)
    risk_factors: OsteoFlagRiskFactors
    bmd: OsteoFlagBmd


class OsteoFlagAudit(BaseModel):
    inputs_used: List[str]
    logic_trace: str


class OsteoFlagResponse(BaseModel):
    screening_flag: Literal["flag", "no_flag", "needs_review"]
    risk_score_0_100: int
    risk_band: Literal["low", "moderate", "high", "very_high"]
    urgency: Literal["routine", "soon", "priority"]
    summary_one_liner: str
    recommendation_clinician: str
    patient_facing_message: str
    safety_disclaimer: str
    audit: OsteoFlagAudit


class OsteoFlagDetectRequest(BaseModel):
    patient_id: str = Field(..., min_length=1)
    screening_input: OsteoFlagInput
    document_type: Optional[str] = None
    image_quality_insufficient: Optional[bool] = False


class OsteoFlagDetectResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    
    result: OsteoFlagResponse
    document_id: str
    document_url: Optional[str] = None
    document_name: Optional[str] = None
    document_type: Optional[str] = None
    document_content_type: Optional[str] = None
    record_id: str
    model_used: str
