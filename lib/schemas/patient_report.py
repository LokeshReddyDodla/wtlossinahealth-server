from enum import Enum
from uuid import UUID
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ReportTypeLiteral(str, Enum):
    pdf = "pdf"
    docx = "docx"
    csv = "csv"
    image = "image"
    other = "other"


class PatientReportBase(BaseModel):
    patient_id: UUID
    report_type: ReportTypeLiteral
    file_name: str
    file_type: str
    file_url: str
    # content_extracted: Optional[str] = None
    uploaded_by_id: Optional[str] = None
    uploaded_by_type: Optional[str] = None


class PatientReportCreate(PatientReportBase):
    pass


class PatientReportUpdate(BaseModel):
    report_type: Optional[ReportTypeLiteral] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    # content_extracted: Optional[str] = None
    uploaded_by_id: Optional[str] = None
    uploaded_by_type: Optional[str] = None


class PatientReport(PatientReportBase):
    report_id: UUID
    uploaded_at: datetime

    class Config:
        from_attributes = True
