from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DomainName(str, Enum):
    MEAL = "meal"
    CGM = "cgm"
    SMBG = "smbg"
    FITNESS = "fitness"
    PROFILE = "profile"
    DOCUMENTS = "documents"
    SLEEP = "sleep"
    VITALS = "vitals"
    PATIENT_SUMMARY = "patient_summary"
    WORKOUT = "workout"


class ConversationMessageKind(str, Enum):
    FRESH_QUERY = "fresh_query"
    FOLLOW_UP = "follow_up"
    CLARIFICATION_ANSWER = "clarification_answer"
    CONVERSATIONAL = "conversational"
    GOAL_UPDATE = "goal_update"
    PREFERENCE_UPDATE = "preference_update"


class ResponseMode(str, Enum):
    LIST = "list"
    SUMMARIZE = "summarize"
    EVALUATE = "evaluate"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    CLARIFY = "clarify"


class PatientMemoryFact(BaseModel):
    key: str
    value: Any
    source: str = "user"
    confidence: float = 1.0
    confirmed: bool = True
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ThreadState(BaseModel):
    thread_id: str
    patient_id: Optional[str] = None
    active_domains: List[DomainName] = Field(default_factory=list)
    active_task_type: Optional[ResponseMode] = None
    active_goal: Optional[str] = None
    active_date_scope: Optional[str] = None
    last_assistant_question: Optional[str] = None
    pending_slots: List[str] = Field(default_factory=list)
    summary: Optional[str] = None
    last_assistant_response: Optional[str] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConversationContext(BaseModel):
    message_kind: ConversationMessageKind
    user_message: str
    normalized_message: str
    recent_messages: List[Dict[str, str]] = Field(default_factory=list)
    inherited_domains: List[DomainName] = Field(default_factory=list)
    inherited_goal: Optional[str] = None
    inherited_date_scope: Optional[str] = None
    pending_slots: List[str] = Field(default_factory=list)
    explicit_facts: List[PatientMemoryFact] = Field(default_factory=list)
    compaction_summary: Optional[str] = None
    context_notes: List[str] = Field(default_factory=list)

    def system_note(self) -> Optional[str]:
        if not self.context_notes:
            return None
        return "\n".join(self.context_notes)


class IntentPlan(BaseModel):
    domains: List[DomainName] = Field(default_factory=list)
    response_mode: ResponseMode = ResponseMode.CLARIFY
    confidence: float = 0.0
    clarifying_required: bool = False
    inherited_from_context: bool = False
    has_temporal_scope: bool = False
    requested_goal: Optional[str] = None
    date_scope_label: Optional[str] = None
    notes: List[str] = Field(default_factory=list)


class RetrievalPlan(BaseModel):
    primary_domains: List[DomainName] = Field(default_factory=list)
    enrichment_domains: List[DomainName] = Field(default_factory=list)
    use_patient_summary: bool = False
    use_qdrant: bool = True
    use_raw_payloads: bool = True
    result_limit: int = 24
    lookback_days: Optional[int] = None
    playbooks: List[str] = Field(default_factory=list)
    tool_chain: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class AnalysisSnapshot(BaseModel):
    snapshot_type: str = "health_query_analysis"
    patient_id: Optional[str] = None
    thread_id: Optional[str] = None
    domains: List[DomainName] = Field(default_factory=list)
    response_mode: ResponseMode = ResponseMode.SUMMARIZE
    summary: Dict[str, Any] = Field(default_factory=dict)
    highlights: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConversationCompaction(BaseModel):
    thread_id: str
    patient_id: Optional[str] = None
    summary: str
    domains: List[DomainName] = Field(default_factory=list)
    active_goal: Optional[str] = None
    active_date_scope: Optional[str] = None
    turn_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ResponseDraft(BaseModel):
    system_addendum: str
    analysis_payload: str
    formatted_context: str = ""
    style_notes: List[str] = Field(default_factory=list)


class ToolExecutionResult(BaseModel):
    payload_items: List[Dict[str, Any]] = Field(default_factory=list)
    search_confidence: Optional[float] = None
    executed_tools: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    degraded_tools: List[str] = Field(default_factory=list)
