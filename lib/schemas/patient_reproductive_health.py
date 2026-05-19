from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class PatientReproductiveHealthBase(BaseModel):
    is_pregnant: Optional[bool] = None
    pregnancy_weeks: Optional[int] = None
    menopause_status: Optional[str] = None
    period_regularity: Optional[str] = None
    uses_contraception: Optional[bool] = None


class PatientReproductiveHealthCreate(PatientReproductiveHealthBase):
    pass


class PatientReproductiveHealth(PatientReproductiveHealthBase):
    patient_id: UUID

    class Config:
        from_attributes = True
