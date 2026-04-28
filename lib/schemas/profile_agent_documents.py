"""Schemas for the medical documents sub-feature of the profile agent.

Documents are stored in the existing Mongo `patient_documents` collection
(shared with care-provider uploads). This module defines:

  * Request/response shapes for the patient-facing endpoints under
    `/profile-agent/documents/...`.
  * The structured `Finding` shape parsed out of each document by the
    `extract_document_findings` arq task.
  * The `LinkGroup` shape returned by the timeline + overview endpoints,
    grouping recurring findings across documents.
  * The LLM output schemas used by `findings_llm.py` and `overview_llm.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


FindingType = Literal["lab", "medication", "diagnosis", "vital", "imaging", "note"]
CodeSystem = Literal["loinc", "rxnorm", "icd10", "snomed"]
ParseStatus = Literal["pending", "extracting", "parsed", "failed"]


class Finding(BaseModel):
    finding_type: FindingType
    code_system: Optional[CodeSystem] = None
    code: Optional[str] = None
    name: str
    name_normalized: str
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None
    reference_range_low: Optional[float] = None
    reference_range_high: Optional[float] = None
    observed_at: Optional[datetime] = None


class FindingsExtraction(BaseModel):
    """LLM output from `findings_llm.extract`."""

    findings: List[Finding] = Field(default_factory=list)


class LinkOccurrence(BaseModel):
    document_id: str
    document_date: Optional[datetime] = None
    observed_at: Optional[datetime] = None
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    unit: Optional[str] = None


class LinkGroup(BaseModel):
    link_group_id: str
    code_system: Optional[CodeSystem] = None
    code: Optional[str] = None
    name: str
    finding_type: FindingType
    occurrences: List[LinkOccurrence] = Field(default_factory=list)


class FileMeta(BaseModel):
    url: str
    type: str
    name: str
    uploaded_at: Optional[datetime] = None


class DocumentSummary(BaseModel):
    """Shape returned in the documents list endpoint."""

    id: str
    patient_id: str
    file: FileMeta
    category: str
    summary_text: Optional[str] = None
    document_date: Optional[datetime] = None
    parse_status: ParseStatus = "pending"
    parse_error: Optional[str] = None
    created_at: Optional[datetime] = None
    uploaded_by: Optional[Dict[str, Any]] = None


class DocumentDetail(DocumentSummary):
    """Single document with findings + a presigned download URL."""

    findings: List[Finding] = Field(default_factory=list)
    download_url: Optional[str] = None


class TimelineEntry(BaseModel):
    id: str
    file_name: str
    category: str
    summary_text: Optional[str] = None
    document_date: Optional[datetime] = None
    parse_status: ParseStatus = "pending"
    finding_count: int = 0


class TimelineResponse(BaseModel):
    documents: List[TimelineEntry] = Field(default_factory=list)
    link_groups: List[LinkGroup] = Field(default_factory=list)


class OverviewResponse(BaseModel):
    patient_id: str
    summary_text: Optional[str] = None
    key_observations: List[str] = Field(default_factory=list)
    link_groups: List[LinkGroup] = Field(default_factory=list)
    source_document_ids: List[str] = Field(default_factory=list)
    latest_document_date: Optional[datetime] = None
    document_count: int = 0
    updated_at: Optional[datetime] = None


class OverviewNarrative(BaseModel):
    """LLM output from `overview_llm.generate_narrative`."""

    summary_text: str
    key_observations: List[str] = Field(default_factory=list)


class DocumentsSection(BaseModel):
    is_complete: bool = False
    is_mandatory: bool = False
    skipped: bool = False


class StartDocumentsResponse(BaseModel):
    greeting: str
    has_prior_uploads: bool
    documents_section: DocumentsSection


class SkipDocumentsResponse(BaseModel):
    documents_section: DocumentsSection


class DeleteDocumentResponse(BaseModel):
    deleted: bool = True


class UploadResultItem(BaseModel):
    file_name: str
    status: Literal["success", "failed"]
    document_id: Optional[str] = None
    error: Optional[str] = None
