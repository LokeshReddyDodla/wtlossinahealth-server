import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    Column,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)

from lib.models import Base


class CareIntentEvent(Base):
    """One day's adherence verdict for one care intent — the record behind
    "did what I asked actually happen". Written by the monitor's morning
    scan (evaluating the completed previous day); one row per intent per day
    (re-evaluation upserts).
    """

    __tablename__ = "care_intent_events"

    care_intent_event_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    care_intent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("care_intents.care_intent_id"),
        nullable=False,
        index=True,
    )
    patient_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    event_date = Column(Date, nullable=False)
    status = Column(String(10), nullable=False)  # followed|missed|unclear
    # Barrier context when visible in the day's data ("knee pain logged",
    # "no dinner logged at all") — reaches the provider, not just a "missed".
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now().replace(tzinfo=None))

    __table_args__ = (
        UniqueConstraint("care_intent_id", "event_date", name="uq_care_intent_event_day"),
    )
