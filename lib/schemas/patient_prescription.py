from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime

from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel


class PatientPrescriptionMedicineSchema(BaseModel):
    brand_name: Optional[str]
    generic_name: Optional[str]
    formulation: Optional[str]
    strength: Optional[str]
    frequency: Optional[str]
    duration: Optional[str]
    before_after_food: Optional[str]
    route: Optional[str]
    purpose: Optional[str]
    possible_side_effects: Optional[List[str]]
    instructions: Optional[str]
    explanation: str

    class Config:
        from_attributes = True


class PatientPrescriptionBase(BaseModel):
    doctor_name: str
    prescription_date: str
    prescription_file_url: str


class PatientPrescriptionCreate(PatientPrescriptionBase):
    general_advice: Optional[str] = None
    follow_up_required: Optional[bool] = False
    follow_up_in_days: Optional[int] = None
    overall_summary: Optional[str] = None
    source: Optional[str] = "ai"
    is_analyzed: Optional[bool] = True
    medicines: List[PatientPrescriptionMedicineSchema]


class PatientPrescriptionRead(PatientPrescriptionBase):
    prescription_id: UUID
    patient_id: UUID
    general_advice: Optional[str]
    follow_up_required: Optional[bool]
    follow_up_in_days: Optional[int]
    overall_summary: Optional[str]
    source: str
    analyzed: bool
    created_at: datetime
    updated_at: datetime
    medicines: List[PatientPrescriptionMedicineSchema]

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj):
        state = obj._sa_instance_state

        kwargs = {
            name: getattr(obj, name)
            for name in cls.model_fields
            if name in state.dict or name not in state.unloaded
        }

        return cls(**kwargs)
