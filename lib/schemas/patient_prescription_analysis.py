from typing import List, Optional

from pydantic import BaseModel, Field


class PrescriptionMedicine(BaseModel):
    name: str = Field(description="Name of the medicine (e.g., 'Paracetamol')")
    dosage: str = Field(description="Dosage details (e.g., '500mg')")
    frequency: str = Field(
        description="How often the medicine should be taken (e.g., 'twice a day', 'once before meal')"
    )
    duration: str = Field(
        description="Duration for which the medicine should be taken (e.g., '5 days', '2 weeks')"
    )
    purpose: Optional[str] = Field(
        default=None,
        description="Purpose of the medicine (e.g., 'Fever reduction')",
    )
    possible_side_effects: Optional[List[str]] = Field(
        default=None,
        description="Possible side effects associated with the medicine (e.g., ['drowsiness', 'nausea'])",
    )
    instructions: Optional[str] = Field(
        default=None,
        description="Any additional instructions (e.g., 'Take with food', 'Avoid alcohol')",
    )
    explanation: str = Field(
        description="Simple explanation of what this medicine is for, how to take it, and any precautions"
    )

    class Config:
        from_attributes = True


class PrescriptionAnalysisResponse(BaseModel):
    doctor_name: str = Field(description="Name of the prescribing doctor")
    prescription_date: str = Field(
        description="Date the prescription was issued (e.g., '2025-07-01')"
    )
    medicines: List[PrescriptionMedicine] = Field(
        description="List of medicines prescribed with their full details"
    )
    general_advice: Optional[str] = Field(
        default=None,
        description="Any general health advice or notes provided in the prescription",
    )
    follow_up_required: Optional[bool] = Field(
        default=False,
        description="Whether a follow-up appointment or consultation is recommended",
    )
    follow_up_in_days: Optional[int] = Field(
        default=None,
        description="If follow-up is needed, in how many days (e.g., 7)",
    )
    overall_summary: Optional[str] = Field(
        default=None,
        description="A general summary of how this prescription helps the patient and important things to remember",
    )

    class Config:
        from_attributes = True
