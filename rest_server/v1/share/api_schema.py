from enum import Enum
from typing import Optional

from pydantic import BaseModel


class SharePillarKey(str, Enum):
    NUTRITION = "nutrition"
    MOVEMENT = "movement"
    SLEEP = "sleep"
    GLUCOSE = "glucose"
    MOOD = "mood"
    WORKOUTS = "workouts"
    VITALS = "vitals"


ALL_PILLAR_KEYS = {p.value for p in SharePillarKey}


class ShareMetric(BaseModel):
    label: str
    value: float | str
    unit: str = ""


class SharePillar(BaseModel):
    key: SharePillarKey
    primary: ShareMetric
    secondary: list[ShareMetric] = []
    delta_percent: Optional[float] = None


class ShareDailyResponse(BaseModel):
    date: str
    headline: Optional[str] = None
    pillars: list[SharePillar]
