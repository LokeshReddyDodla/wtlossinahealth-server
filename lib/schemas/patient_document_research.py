from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

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


class PatientDocumentResearchSummaryRequest(BaseModel):
    document_ids: Optional[List[str]] = Field(
        None,
        min_length=1,
        description="Patient document IDs stored in MongoDB",
    )
    sources: Optional[List[PatientDocumentResearchSource]] = Field(
        None,
        min_length=1,
        description="Selected research sources across documents or prescriptions",
    )
    question: Optional[str] = Field(
        None,
        description="Optional research question to answer using the selected documents",
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Optional conversation ID to keep research chats contextual",
    )

    @model_validator(mode="before")
    def require_documents_or_sources(cls, data):
        if isinstance(data, dict):
            document_ids = data.get("document_ids")
            sources = data.get("sources")
            if not document_ids and not sources:
                raise ValueError(
                    "At least one document or source must be selected"
                )
        return data


class PatientDocumentResearchSummaryResponse(BaseModel):
    conversation_id: str
    summary: str
    follow_up_questions: List[str] = Field(default_factory=list)
    source_documents: List[PatientDocumentResearchDocument] = Field(
        default_factory=list
    )


class PatientDocumentResearchChatRequest(BaseModel):
    document_ids: Optional[List[str]] = Field(
        None,
        min_length=1,
        description="Patient document IDs to use for answering the question",
    )
    sources: Optional[List[PatientDocumentResearchSource]] = Field(
        None,
        min_length=1,
        description="Selected research sources across documents or prescriptions",
    )
    question: str = Field(..., min_length=1, description="Doctor question")
    conversation_id: Optional[str] = Field(
        None,
        description="Conversation ID returned from the summary endpoint",
    )

    @model_validator(mode="before")
    def require_documents_or_sources(cls, data):
        if isinstance(data, dict):
            document_ids = data.get("document_ids")
            sources = data.get("sources")
            if not document_ids and not sources:
                raise ValueError(
                    "At least one document or source must be selected"
                )
        return data


class PatientDocumentResearchChatResponse(BaseModel):
    conversation_id: str
    answer: str
    follow_up_questions: List[str] = Field(default_factory=list)
    source_documents: List[PatientDocumentResearchDocument] = Field(
        default_factory=list
    )
