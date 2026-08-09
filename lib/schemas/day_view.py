"""Typed payload for the unified day view (provider dashboard hub).

The contract every downstream layer conforms to. A lean overview — spine +
on-curve markers + rails + one rollup per domain. Full per-domain detail is NOT
here; it loads on demand from the domain report addressed by `reports[domain]`.

Spec: docs/day-timeline-resolver.md
"""

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# (hour_of_day 0..24 as float, value) — the x is patient-local decimal hours.
Point = tuple[float, float]
# (start_hour, end_hour) window.
Span = tuple[float, float]


class SpineSource(str, Enum):
    """Which physiological series carries the plot — highest fidelity available."""

    cgm = "cgm"      # continuous glucose line
    smbg = "smbg"    # finger-stick dots, never joined
    hr = "hr"        # continuous heart rate (own axis, not a glucose surrogate)
    none = "none"    # no plot; behavioral lanes only


SleepStage = Literal["deep", "light", "rem", "awake"]
# (start_hour, end_hour, stage) — real spans from sleep_data, not a composition guess.
StageSpan = tuple[float, float, SleepStage]


class SpineEvent(BaseModel):
    """A CGM excursion window (source=cgm only)."""

    type: Literal["hypo", "hyper"]
    start: float
    end: float
    peak: float


class Spine(BaseModel):
    source: SpineSource
    unit: str | None = None          # "mg/dL" for cgm/smbg, "bpm" for hr, None for none
    points: list[Point] = []         # dots (not a line) when source=smbg
    band: Span | None = None         # target [70,180]; resting [60,100] for hr
    events: list[SpineEvent] = []    # populated for source=cgm only


class MealMarker(BaseModel):
    t: float
    name: str
    type: str | None = None
    delta_mgdl: float | None = None          # glucose_response.delta (cgm only)
    score: float | None = None               # meal quality 0..1
    comparison: Literal["within", "above", "below"] | None = None
    predicted: Span | None = None            # predicted delta band
    carbs_g: float | None = None


class SymptomMarker(BaseModel):
    t: float
    name: str
    severity: int | None = None              # 1..5


class WorkoutMarker(BaseModel):
    t: float
    type: str
    minutes: int | None = None
    kcal: float | None = None


class OnCurve(BaseModel):
    """Markers that share the spine's y-axis — placed on the curve."""

    meals: list[MealMarker] = []
    symptoms: list[SymptomMarker] = []
    workouts: list[WorkoutMarker] = []


class StepsLane(BaseModel):
    hourly: list[Point] = []                 # 24 hourly buckets
    inactive: list[Span] = []                # "no steps logged" windows (never "sedentary")


class SleepLane(BaseModel):
    stages: list[StageSpan] = []
    asleep_h: float | None = None
    efficiency: float | None = None


class DoseMarker(BaseModel):
    t: float
    slot: str                                # morning | afternoon | evening | night
    label: str                               # short glyph, e.g. "M" / "S"
    name: str | None = None                  # medication name(s), e.g. "Metformin 500mg"
    status: Literal["taken", "missed", "scheduled"] = "scheduled"
    taken: bool                              # shorthand for status == "taken"
    at: str | None = None                    # HH:MM when taken, else None


class MoodMarker(BaseModel):
    t: float
    level: int                               # 1..5
    emoji: str | None = None


class VitalMarker(BaseModel):
    t: float
    systolic: float | None = None
    diastolic: float | None = None


class Lanes(BaseModel):
    """Signals with their own units — thin rails beneath the plot."""

    steps: StepsLane = Field(default_factory=StepsLane)
    sleep: SleepLane = Field(default_factory=SleepLane)
    doses: list[DoseMarker] = []
    mood: list[MoodMarker] = []              # discrete markers; NEVER a connecting line
    vitals: list[VitalMarker] = []
    hr: list[Point] = []                     # hourly-average bpm; empty when HR is the spine


class GlucoseRollup(BaseModel):
    tir_pct: float | None = None
    avg: float | None = None
    gri: float | None = None
    # [<54, 54-70, 70-180, 180-250, >250] percentages.
    bands: list[float] | None = None


class NutritionRollup(BaseModel):
    kcal: float | None = None
    kcal_target: float | None = None
    meals: int | None = None


class SleepRollup(BaseModel):
    asleep_h: float | None = None
    efficiency: float | None = None


class ActivityRollup(BaseModel):
    steps: int | None = None
    steps_goal: int | None = None
    workouts: int | None = None


class VitalsRollup(BaseModel):
    bp_latest: str | None = None
    hr_avg: float | None = None


class CareRollup(BaseModel):
    doses_taken: int = 0
    doses_total: int = 0
    tasks_done: int = 0
    tasks_total: int = 0


class TaskItem(BaseModel):
    title: str
    status: Literal["pending", "completed", "skipped", "expired"]
    task_type: str                           # e.g. HIT_STEP_GOAL, TAKE_MEDICATION_MORNING
    category: str                            # source_type: medication | diet_plan | quest | ...
    xp: int = 0
    at: str | None = None                    # HH:MM completed, else None
    target: float | None = None              # for progress tasks (e.g. steps 8200/10000)
    current: float | None = None


class Header(BaseModel):
    """One rollup number per domain — the day at a glance."""

    glucose: GlucoseRollup = Field(default_factory=GlucoseRollup)
    nutrition: NutritionRollup = Field(default_factory=NutritionRollup)
    sleep: SleepRollup = Field(default_factory=SleepRollup)
    activity: ActivityRollup = Field(default_factory=ActivityRollup)
    vitals: VitalsRollup = Field(default_factory=VitalsRollup)
    care: CareRollup = Field(default_factory=CareRollup)


class InsightMarker(BaseModel):
    """A proactive-monitor insight.

    `t` is the source event's local hour (created_at for cron insights); it is
    NOT a spine y-value.
    """

    t: float
    insight_id: str | None = None
    severity: str                            # info | attention | warning | alert
    category: str
    title: str | None = None
    message: str
    suggested_query: str | None = None
    entity_type: str | None = None           # meal | smbg | symptom — source anchor
    entity_id: str | None = None
    recurring_days: int | None = None        # consecutive-day streak once a pattern escalates


class DayAlert(BaseModel):
    """A deterministic clinical flag for the day — threshold math over already
    computed values, framed for a clinician. NOT a patient insight: no LLM, no
    coaching voice.
    """

    severity: Literal["critical", "attention", "info"]
    category: str                            # glucose_low | glucose_high | tir_low | bp_high | doses_missed | no_glucose
    label: str                               # clinical short text, e.g. "2 lows · dipped to 48 mg/dL"
    t: float | None = None                   # local hour when the flag is event-anchored (e.g. a BP reading)


class DayView(BaseModel):
    date: date
    tz: str
    spine: Spine
    on_curve: OnCurve = Field(default_factory=OnCurve)
    lanes: Lanes = Field(default_factory=Lanes)
    header: Header = Field(default_factory=Header)
    insights: list[InsightMarker] = []
    alerts: list[DayAlert] = []
    tasks: list[TaskItem] = []
    # Deterministic report IDs for drill-down — derived at read, never stored.
    reports: dict[str, str] = {}
