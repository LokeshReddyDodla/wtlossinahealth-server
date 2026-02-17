from datetime import date
from typing import List

from pydantic import BaseModel, Field


class DateDataAvailability(BaseModel):
    """Data availability for a single date"""

    date: date
    smbg_count: int = 0
    meal_count: int = 0
    fitness_count: int = 0
    cgm_count: int = 0
    vitals_count: int = 0

    # Boolean flags for quick checks
    has_smbg: bool = False
    has_meal: bool = False
    has_fitness: bool = False
    has_cgm: bool = False
    has_vitals: bool = False


class PatientDataAvailabilityResponse(BaseModel):
    """Response model for patient data availability"""

    patient_id: str
    target_date: date
    availability: List[DateDataAvailability]
