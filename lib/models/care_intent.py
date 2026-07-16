import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Column,
    Date,
    DateTime,
    Index,
    String,
    Text,
)
from sqlalchemy import ForeignKey

from lib.models import Base


class CareIntent(Base):
    """One care-provider instruction for one patient ("keep reminding him to
    walk after dinner"). N providers author independently — each row is one
    attributed intent; the AI merges active rows at read time. The provider's
    original sentence is the source of truth for voice; the structured fields
    drive scheduling and context injection.
    """

    __tablename__ = "care_intents"

    care_intent_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id"),
        nullable=False,
        index=True,
    )

    # Attribution — the entire point of the feature. author_name is
    # denormalized so scan-time context needs no join; display-only.
    author_id = Column(UUID(as_uuid=True), nullable=False)
    author_role = Column(String(50), nullable=False)
    author_name = Column(String(255), nullable=False)

    # The sentence the provider typed — canonical for tone/attribution.
    original_text = Column(Text, nullable=False)

    # LLM-structured fields (validated against ai_foundation care_intents
    # contracts at the API edge; strings here so migrations never chase enums)
    intent_type = Column(String(20), nullable=False)  # remind|watch|encourage|restrict|escalate
    domain = Column(String(30), nullable=False)
    trigger_condition = Column(Text, nullable=True)  # human-readable condition, LLM-inferred
    cadence = Column(String(10), nullable=False, default="passive")  # daily|event|passive
    patient_summary = Column(Text, nullable=False)  # friendly, patient-facing, English canonical

    # v2 schema room: adherence tracking evaluates against this.
    success_criteria = Column(Text, nullable=True)

    # Every intent expires — stale instructions must never nag forever.
    review_date = Column(Date, nullable=False)
    status = Column(String(10), nullable=False, default="active", index=True)  # active|paused|expired
    # When the author was last pinged about repeated misses — one ping per
    # miss-streak, not one per day.
    escalated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now().replace(tzinfo=None))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now().replace(tzinfo=None),
        onupdate=lambda: datetime.now().replace(tzinfo=None),
    )

    __table_args__ = (
        Index("ix_care_intents_patient_status", "patient_id", "status"),
    )
