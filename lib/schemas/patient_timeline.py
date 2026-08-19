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


class DaySummary(BaseModel):
    """Ambient metrics for the day. A metric is None (never 0) when the day has
    no reading for it — 0 would read as a real value and imply a gap that isn't
    there."""

    steps: int | None = None
    active_energy_kcal: float | None = None
    distance_km: float | None = None
    resting_hr: int | None = None
    avg_hr: int | None = None
    min_hr: int | None = None
    max_hr: int | None = None
    avg_spo2: float | None = None
    avg_glucose: int | None = None
    time_in_range: float | None = None
    sleep_hours: float | None = None
    sleep_quality: str | None = None


class TimelineResponse(BaseModel):
    date: date
    patient_id: str
    event_count: int
    events: list[TimelineEvent]
    summary: DaySummary | None = None
