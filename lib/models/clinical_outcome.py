import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID

from lib.models import Base


class AdviceEvent(Base):
    """Append-only ledger of clinical advice given to patients.

    Only SUGGEST-mode events with cited levers are logged (Forge P1).
    Immutable after insert — follow-ups go in AdviceFollowup.
    """
    __tablename__ = "advice_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    track = Column(String(20), nullable=False)          # glucose | obesity
    trigger = Column(String(100), nullable=False)       # e.g. high_carb_breakfast
    meal_slot = Column(String(20), nullable=True)       # breakfast | lunch | dinner | snack
    output_mode = Column(String(20), nullable=False, default="SUGGEST")
    lever_name = Column(String(50), nullable=True)      # protein_pair, fiber, etc.
    lever_say = Column(Text, nullable=True)             # human-readable advice
    predicted_delta = Column(Float, nullable=True)      # expected effect (mg/dL or %)
    cite = Column(String(200), nullable=True)           # evidence citation
    confidence = Column(String(20), nullable=True)      # high | moderate | low
    meal_macros = Column(JSON, nullable=True)           # {carb, protein, fiber, fat, cal}
    meal_time = Column(DateTime(timezone=True), nullable=True)
    contract_snapshot = Column(JSON, nullable=True)     # full engine contract for audit
    logged_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    followed_up = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_advice_events_patient_pending", "patient_id", "followed_up",
              postgresql_where=(~followed_up)),
        Index("ix_advice_events_patient_track", "patient_id", "track", "trigger"),
    )


class AdviceFollowup(Base):
    """Records whether advice actually worked. Linked 1:1 to an AdviceEvent."""
    __tablename__ = "advice_followups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # unique=True enforces the 1:1 at the DB — without it, two concurrent
    # follow-up workers both reading the event as pending would insert
    # duplicate rows and double-count efficacy in rollup().
    event_id = Column(UUID(as_uuid=True), ForeignKey("advice_events.id"), nullable=False, unique=True, index=True)
    complied = Column(Boolean, nullable=True)           # None = unknown
    compliance_evidence = Column(Text, nullable=True)   # what we observed
    observed_delta = Column(Float, nullable=True)       # actual spike change (mg/dL or %)
    outcome_vs_predicted = Column(String(20), nullable=True)  # as_predicted | opposite | unknown
    followup_meal_macros = Column(JSON, nullable=True)  # the follow-up meal's macros
    cgm_pre = Column(Float, nullable=True)              # pre-meal glucose at advice time
    cgm_peak = Column(Float, nullable=True)             # peak post-meal glucose at advice time
    followup_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ClinicalDecisionAudit(Base):
    """Immutable audit trail of every clinical decision the engine makes.

    Append-only. Never updated or deleted. Industry standard for clinical AI
    (HIPAA audit trail, 6-year retention).
    """
    __tablename__ = "clinical_decision_audit"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    output_mode = Column(String(20), nullable=False)    # SUGGEST | REINFORCE | FLAG_PHYSIOLOGY | STATE_FACTS | SAFETY
    safety_flags = Column(JSON, nullable=True)          # ["NO_MED_CHANGE", "PRE_HYPO", ...]
    attribution_label = Column(String(30), nullable=True)
    confidence = Column(String(20), nullable=True)
    rise_mgdl = Column(Float, nullable=True)
    has_cgm = Column(Boolean, nullable=True)
    lever_name = Column(String(50), nullable=True)
    contract_snapshot = Column(JSON, nullable=True)     # full contract for reproducibility
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_clinical_audit_patient_time", "patient_id", "created_at"),
    )
