from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator


class AssignmentStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PatientPackageAssignmentBase(BaseModel):
    package_id: UUID
    patient_id: UUID
    start_date: date
    end_date: date
    status: Optional[AssignmentStatus] = AssignmentStatus.ACTIVE

    @model_validator(mode="before")
    def check_dates(cls, data):
        if "start_date" in data and "end_date" in data:
            if data["end_date"] < data["start_date"]:
                raise ValueError("end_date must be >= start_date")
        return data


class PatientPackageAssignmentCreate(PatientPackageAssignmentBase):
    pass


class PatientPackageAssignmentUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[AssignmentStatus] = None


class PatientPackageAssignment(PatientPackageAssignmentBase):
    assignment_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
