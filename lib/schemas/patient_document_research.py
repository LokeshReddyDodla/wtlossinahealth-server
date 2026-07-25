from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ResearchSourceType = Literal[
    "patient_document",
    "prescription",
]


class PatientDocumentResearchListItem(BaseModel):
    source_type: Optional[ResearchSourceType] = None
    document_id: str
    file_name: Optional[str] = None
    file_url: Optional[str] = None
    mime_type: Optional[str] = None
    category: Optional[str] = None
    document_date: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None
    uploaded_by_type: Optional[str] = None
    summary_preview: Optional[str] = None


class PatientDocumentResearchDocument(PatientDocumentResearchListItem):
    summary_text: Optional[str] = None


class PatientDocumentResearchSource(BaseModel):
    source_type: ResearchSourceType
    source_id: str


class PatientDocumentResearchSelectionItem(BaseModel):
    source_type: ResearchSourceType
    source_id: str
    title: Optional[str] = None
    category: Optional[str] = None
    document_date: Optional[datetime] = None
    summary_preview: Optional[str] = None
    metadata: Optional[dict] = None


class PatientDocumentResearchSelectionResponse(BaseModel):
    items: List[PatientDocumentResearchSelectionItem] = Field(
        default_factory=list
    )
