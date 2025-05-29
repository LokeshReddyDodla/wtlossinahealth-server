from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

from lib.schemas.package import Package


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

    @model_validator(mode="before")
    def check_dates(cls, data):
        if isinstance(data, dict):
            if (
                data.get("start_date") is not None
                and data.get("end_date") is not None
            ):
                if data["end_date"] < data["start_date"]:
                    raise ValueError("end_date must be >= start_date")
        else:
            if data.start_date is not None and data.end_date is not None:
                if data.end_date < data.start_date:
                    raise ValueError("end_date must be >= start_date")
        return data


class PatientPackageAssignmentCreate(PatientPackageAssignmentBase):
    pass


class PatientPackageAssignmentUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[AssignmentStatus] = AssignmentStatus.ACTIVE


class PatientPackageAssignment(PatientPackageAssignmentBase):
    assignment_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PatientPackageAssignmentWithDetail(PatientPackageAssignment):
    package: Optional[Package] = None
