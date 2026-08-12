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
    current: float | None = None
    baseline: float | None = None
    delta: float | None = None


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


class ProgressView(BaseModel):
    range: RangeKey
    resolution: Resolution
    start: date
    end: date
    outcomes: list[Outcome]
    metrics: list[MetricSeries]
    engagement: Engagement
