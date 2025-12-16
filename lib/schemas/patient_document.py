from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class PatientDocumentListItem(BaseModel):
    document_id: str
    file_name: Optional[str] = None
    file_url: Optional[str] = None
    mime_type: Optional[str] = None
    category: Optional[str] = None
    document_date: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None
    uploaded_by_type: Optional[str] = None
    summary_preview: Optional[str] = None


class PatientDocumentSummaryDocument(PatientDocumentListItem):
    summary_text: Optional[str] = None


class PatientDocumentSummaryRequest(BaseModel):
    document_ids: List[str] = Field(
        ...,
        min_length=1,
        description="Patient document IDs stored in MongoDB",
    )
    question: Optional[str] = Field(
        None,
        description="Optional research question to answer using the selected documents",
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Optional conversation ID to keep research chats contextual",
    )


class PatientDocumentSummaryResponse(BaseModel):
    conversation_id: str
    summary: str
    follow_up_questions: List[str] = Field(default_factory=list)
    source_documents: List[PatientDocumentSummaryDocument] = Field(
        default_factory=list
    )


class PatientDocumentChatRequest(BaseModel):
    document_ids: List[str] = Field(
        ...,
        min_length=1,
        description="Patient document IDs to use for answering the question",
    )
    question: str = Field(..., min_length=1, description="Doctor question")
    conversation_id: Optional[str] = Field(
        None,
        description="Conversation ID returned from the summary endpoint",
    )


class PatientDocumentChatResponse(BaseModel):
    conversation_id: str
    answer: str
    follow_up_questions: List[str] = Field(default_factory=list)
    source_documents: List[PatientDocumentSummaryDocument] = Field(
        default_factory=list
    )
