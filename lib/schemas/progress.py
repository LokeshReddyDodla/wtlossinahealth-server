"""Progress trends — typed compose-on-read payload.

`dir` is the direction of *improvement* (up = higher-is-better), so the
frontend colors deltas without hardcoding per-metric rules. `target` is a
clinical threshold on the same side as `dir` when one exists.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel

RangeKey = Literal["1M", "3M", "6M", "1Y"]
Resolution = Literal["weekly", "monthly"]
Direction = Literal["up", "down", "flat"]


class TrendPoint(BaseModel):
    t: str  # bucket-start ISO date
    value: float


class MetricSeries(BaseModel):
    category: str
    key: str
    label: str
    unit: str
    dir: Direction
    target: float | None = None
    points: list[TrendPoint]
    # Raw daily points (deduped by day) for short ranges only; empty on long
    # ranges to bound payload — the bucketed `points` carry the long view.
    daily: list[TrendPoint] = []
    current: float | None = None
    baseline: float | None = None
    delta: float | None = None
    # How much data backs the series, so a provider can judge trust. `note` is a
    # one-line methodology caveat; `low_coverage` means the trend is too sparse
    # to diff, so `delta` is withheld.
    note: str | None = None
    coverage_days: int = 0
    period_days: int = 0
    latest: date | None = None
    low_coverage: bool = False


class CompositionSegment(BaseModel):
    label: str
    value: float
    tone: str  # good | warn | bad | neutral — frontend colors the segment


class Composition(BaseModel):
    """Related metrics that are slices of one whole, shown as a single stacked
    bar instead of separate trend lines — glucose time-in-ranges, calories by
    meal, sleep stages. Values are averaged over days with data."""

    category: str
    key: str
    label: str
    unit: str
    segments: list[CompositionSegment]
    note: str | None = None
    coverage_days: int = 0
    period_days: int = 0
    latest: date | None = None
    low_coverage: bool = False


class Outcome(BaseModel):
    key: str
    label: str
    value: str
    delta: str | None = None
    good: bool | None = None


class Engagement(BaseModel):
    current_streak: int = 0
    longest_streak: int = 0
    completion_pct: float | None = None
    completion_points: list[TrendPoint] = []


class IntentAdherence(BaseModel):
    """One active care-provider instruction and how the patient tracked against
    it over the range. `rate` counts only decided days (followed / missed);
    `unclear` days are shown but excluded from the rate."""

    care_intent_id: str
    summary: str
    author: str
    followed: int = 0
    missed: int = 0
    unclear: int = 0
    rate: float | None = None
    last_note: str | None = None


class ProgressView(BaseModel):
    range: RangeKey
    resolution: Resolution
    start: date
    end: date
    outcomes: list[Outcome]
    metrics: list[MetricSeries]
    engagement: Engagement
    compositions: list[Composition] = []
    care_intents: list[IntentAdherence] = []
