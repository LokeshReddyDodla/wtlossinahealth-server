from typing import List, Optional

from pydantic import BaseModel, Field


class PrescriptionMedicine(BaseModel):
    brand_name: Optional[str] = Field(
        description="Brand name of the medicine (e.g., 'Glycomet', 'Crocin')"
    )
    generic_name: Optional[str] = Field(
        default=None,
        description="Generic name of the medicine (e.g., 'Metformin', 'Paracetamol')",
    )
    formulation: Optional[str] = Field(
        default=None,
        description="Form of medicine (e.g., 'Tablet', 'Syrup', 'Capsule', 'Injection')",
    )
    strength: Optional[str] = Field(
        default=None,
        description="Strength or concentration (e.g., '500 mg', '5 mg/5 ml')",
    )
    frequency: Optional[str] = Field(
        default=None,
        description="Dosage frequency (e.g., '1-0-1', 'SOS', 'Twice a day')",
    )
    duration: Optional[str] = Field(
        default=None,
        description="Duration for which to take the medicine (e.g., '5 Days', '2 Weeks')",
    )
    before_after_food: Optional[str] = Field(
        default=None,
        description="Whether to take before or after food (e.g., 'Before food', 'After food')",
    )
    route: Optional[str] = Field(
        default=None,
        description="Route of administration (e.g., 'Oral', 'IV', 'Topical')",
    )
    instructions: Optional[str] = Field(
        default=None,
        description="Additional instructions (e.g., 'Shake well before use', 'Take with water')",
    )
    purpose: Optional[str] = Field(
        default=None,
        description="Purpose or reason for taking the medicine (e.g., 'For fever reduction')",
    )
    possible_side_effects: Optional[List[str]] = Field(
        default=None,
        description="Possible side effects (e.g., ['Drowsiness', 'Nausea'])",
    )
    explanation: str = Field(
        description="A brief explanation about what the medicine does and how to take it safely"
    )

    class Config:
        from_attributes = True


class PrescriptionAnalysis(BaseModel):
    doctor_name: str = Field(description="Name of the prescribing doctor")
    prescription_date: str = Field(
        description="Date the prescription was issued"
    )
    prescription_file_url: Optional[str] = Field(
        default=None, description="URL of the prescription image/pdf"
    )
    medicines: List[PrescriptionMedicine] = Field(
        description="List of extracted medicines with details"
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


class PrescriptionStructureResponse(BaseModel):
    doctor_name: str = Field(description="Name of the prescribing doctor")
    prescription_date: str = Field(
        description="Date the prescription was issued"
    )
    prescription_file_url: Optional[str] = Field(
        default=None, description="URL of the prescription image/pdf"
    )
    medicines: List[PrescriptionMedicine] = Field(
        description="List of extracted medicines with details"
    )

    class Config:
        from_attributes = True


class PrescriptionAdviceResponse(BaseModel):
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
