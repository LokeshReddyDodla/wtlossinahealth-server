from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel


class TimelineEventType(str, Enum):
    SLEEP = "sleep"
    MEAL = "meal"
    SMBG = "smbg"
    MOOD = "mood"
    SYMPTOM = "symptom"
    WORKOUT = "workout"
    MEDICATION_TAKEN = "medication_taken"
    MEDICATION_MISSED = "medication_missed"
    VITAL = "vital"
    AI_INSIGHT = "ai_insight"
    CGM_EVENT = "cgm_event"
    INACTIVE_PERIOD = "inactive_period"


class TimelineEvent(BaseModel):
    timestamp: datetime
    type: TimelineEventType
    title: str
    subtitle: str | None = None
    data: dict = {}
    entity_id: str | None = None


class TimelineResponse(BaseModel):
    date: date
    patient_id: str
    event_count: int
    events: list[TimelineEvent]
