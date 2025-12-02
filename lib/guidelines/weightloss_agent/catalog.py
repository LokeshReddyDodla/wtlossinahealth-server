"""Static guideline catalog used to source plan targets and coach chips."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class GuidelineMetric:
    metric_id: str
    label: str
    min_value: Optional[float]
    max_value: Optional[float]
    units: str
    cadence: str = "daily"
    notes: Optional[str] = None


@dataclass(frozen=True)
class Guideline:
    guideline_id: str
    title: str
    source: str
    version: str
    metrics: Dict[str, GuidelineMetric]
    focus_habits: List[str]


GUIDELINE_VERSION = "2025.03"

GUIDELINE_CATALOG: Dict[str, Guideline] = {
    "acsm_pa_2025": Guideline(
        guideline_id="acsm_pa_2025",
        title="ACSM Physical Activity Guidelines 2025",
        source="American College of Sports Medicine",
        version=GUIDELINE_VERSION,
        metrics={
            "daily_steps": GuidelineMetric(
                metric_id="daily_steps",
                label="Daily step volume",
                min_value=7000,
                max_value=10500,
                units="steps",
                notes="Range captures baseline to aspirational volume for adults with cardiometabolic risk.",
            ),
            "weekly_minutes_moderate": GuidelineMetric(
                metric_id="weekly_minutes_moderate",
                label="Weekly moderate minutes",
                min_value=150,
                max_value=210,
                units="minutes",
                cadence="weekly",
            ),
        },
        focus_habits=[
            "two 10-minute walks after meals",
            "one strength session every 3 days",
        ],
    ),
    "ada_2025": Guideline(
        guideline_id="ada_2025",
        title="ADA Nutrition + Activity Standards 2025",
        source="American Diabetes Association",
        version=GUIDELINE_VERSION,
        metrics={
            "protein_floor": GuidelineMetric(
                metric_id="protein_floor",
                label="Daily protein minimum",
                min_value=80,
                max_value=120,
                units="grams",
            ),
            "calorie_band": GuidelineMetric(
                metric_id="calorie_band",
                label="Daily calorie band",
                min_value=1400,
                max_value=1800,
                units="kcal",
            ),
            "hydration_oz": GuidelineMetric(
                metric_id="hydration_oz",
                label="Daily hydration target",
                min_value=80,
                max_value=100,
                units="oz",
            ),
        },
        focus_habits=[
            "hydrate before caffeine",
            "protein anchor every meal",
        ],
    ),
}


def get_guideline(guideline_id: str) -> Optional[Guideline]:
    return GUIDELINE_CATALOG.get(guideline_id)


def get_metric_sources(metric_id: str) -> List[str]:
    sources: List[str] = []
    for guideline in GUIDELINE_CATALOG.values():
        if metric_id in guideline.metrics:
            sources.append(guideline.guideline_id)
    return sources


def get_metric(metric_id: str) -> Optional[GuidelineMetric]:
    for guideline in GUIDELINE_CATALOG.values():
        metric = guideline.metrics.get(metric_id)
        if metric:
            return metric
    return None
