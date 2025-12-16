from typing import List, Optional
from pydantic import BaseModel, Field


class PatientPresentation(BaseModel):
    short_summary: Optional[str] = Field(
        default=None, description="1-2 sentence plain summary for patient"
    )
    email_summary: Optional[str] = Field(
        default=None, description="Patient-friendly email-style summary"
    )


class CareProviderPresentation(BaseModel):
    email_summary: Optional[str] = Field(
        default=None,
        description="Clinical email-style summary for care providers",
    )
    detailed_summary: Optional[str] = Field(
        default=None,
        description="Detailed clinical summary for care providers with qualitative observations, no raw numbers",
    )


class InsightsResponse(BaseModel):
    headline: Optional[str] = Field(
        default=None, description="One short headline insight"
    )
    key_points: List[str] = Field(
        default_factory=list,
        description="Up to 4 bullet key points",
    )
    patterns: List[str] = Field(
        default_factory=list,
        description="Up to 4 observed patterns/correlations",
    )
    patient_presentation: PatientPresentation
    care_provider_presentation: CareProviderPresentation

