"""Canonical body-composition metric registry — the single source of truth.

Every device (InBody, Tanita, Seca, DEXA, …) is normalized into these canonical
keys. The registry drives: alias resolution, unit conversion, plausibility
validation, projection into typed DB columns (so trends/BMIQ/cohort queries hit
indexed columns, not JSON), and which BMIQ dimension each metric feeds.

Add a metric here and it flows through normalization, validation, the typed
column, and the trend/BMIQ readers — no code changes elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

LB_TO_KG = 0.45359237
IN_TO_CM = 2.54


class MetricKind(str, Enum):
    MASS = "mass"          # kg (lb auto-converts)
    VOLUME = "volume"      # L
    PERCENT = "percent"    # %
    RATIO = "ratio"        # unitless ratio
    LEVEL = "level"        # ordinal (e.g. visceral fat level)
    AREA = "area"          # cm²
    LENGTH = "length"      # cm (in auto-converts)
    ANGLE = "angle"        # degrees
    INDEX = "index"        # kg/m² (BMI, SMI)
    ENERGY = "energy"      # kcal
    SCORE = "score"        # vendor score


class BmiqDimension(str, Enum):
    ADIPOSITY = "D1_adiposity"
    VISCERAL = "D2_visceral"
    SARCOPENIA = "D3_sarcopenia"
    FLUID = "D4_fluid"


@dataclass(frozen=True)
class MetricSpec:
    key: str                       # canonical snake_case key
    column: str                    # typed DB column on the record
    unit: str                      # canonical unit
    kind: MetricKind
    low: float                     # plausibility floor
    high: float                    # plausibility ceiling
    bmiq: BmiqDimension | None = None
    signed: bool = False           # allows negatives (control targets)


# key, column, unit, kind, low, high, bmiq, signed
_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("weight", "weight_kg", "kg", MetricKind.MASS, 10, 500),
    MetricSpec("bmi", "bmi", "kg/m2", MetricKind.INDEX, 5, 100, BmiqDimension.ADIPOSITY),
    MetricSpec("obesity_degree", "obesity_degree_pct", "%", MetricKind.PERCENT, 30, 400),
    MetricSpec("device_score", "device_score", "score", MetricKind.SCORE, 0, 120),
    MetricSpec("total_body_water", "total_body_water_l", "L", MetricKind.VOLUME, 5, 100),
    MetricSpec("intracellular_water", "intracellular_water_l", "L", MetricKind.VOLUME, 0, 80),
    MetricSpec("extracellular_water", "extracellular_water_l", "L", MetricKind.VOLUME, 0, 60),
    MetricSpec("protein", "protein_kg", "kg", MetricKind.MASS, 0, 50),
    MetricSpec("minerals", "minerals_kg", "kg", MetricKind.MASS, 0, 20),
    MetricSpec("bone_mineral_content", "bone_mineral_content_kg", "kg", MetricKind.MASS, 0, 10),
    MetricSpec("body_fat_mass", "body_fat_mass_kg", "kg", MetricKind.MASS, 0, 300),
    MetricSpec("soft_lean_mass", "soft_lean_mass_kg", "kg", MetricKind.MASS, 0, 150),
    MetricSpec("fat_free_mass", "fat_free_mass_kg", "kg", MetricKind.MASS, 0, 200),
    MetricSpec("skeletal_muscle_mass", "skeletal_muscle_mass_kg", "kg", MetricKind.MASS, 1, 150, BmiqDimension.SARCOPENIA),
    MetricSpec("body_cell_mass", "body_cell_mass_kg", "kg", MetricKind.MASS, 0, 100),
    MetricSpec("percent_body_fat", "percent_body_fat", "%", MetricKind.PERCENT, 0, 80, BmiqDimension.ADIPOSITY),
    MetricSpec("visceral_fat_level", "visceral_fat_level", "level", MetricKind.LEVEL, 0, 60, BmiqDimension.VISCERAL),
    MetricSpec("visceral_fat_area", "visceral_fat_area_cm2", "cm2", MetricKind.AREA, 0, 1000, BmiqDimension.VISCERAL),
    MetricSpec("waist_hip_ratio", "waist_hip_ratio", "ratio", MetricKind.RATIO, 0.4, 1.5, BmiqDimension.VISCERAL),
    MetricSpec("waist_circumference", "waist_cm", "cm", MetricKind.LENGTH, 20, 300, BmiqDimension.VISCERAL),
    MetricSpec("hip_circumference", "hip_cm", "cm", MetricKind.LENGTH, 20, 300),
    MetricSpec("ecw_tbw_ratio", "ecw_tbw_ratio", "ratio", MetricKind.RATIO, 0.2, 0.7, BmiqDimension.FLUID),
    MetricSpec("whole_body_phase_angle", "whole_body_phase_angle_deg", "deg", MetricKind.ANGLE, 0, 20),
    MetricSpec("skeletal_muscle_index", "skeletal_muscle_index", "kg/m2", MetricKind.INDEX, 2, 20, BmiqDimension.SARCOPENIA),
    MetricSpec("basal_metabolic_rate", "basal_metabolic_rate_kcal", "kcal", MetricKind.ENERGY, 500, 5000),
    MetricSpec("target_weight", "target_weight_kg", "kg", MetricKind.MASS, 0, 500),
    MetricSpec("weight_control", "weight_control_kg", "kg", MetricKind.MASS, -300, 300, signed=True),
    MetricSpec("fat_control", "fat_control_kg", "kg", MetricKind.MASS, -300, 300, signed=True),
    MetricSpec("muscle_control", "muscle_control_kg", "kg", MetricKind.MASS, -200, 200, signed=True),
)

SPEC_BY_KEY: dict[str, MetricSpec] = {s.key: s for s in _SPECS}
CANONICAL_KEYS: frozenset[str] = frozenset(SPEC_BY_KEY)
# Columns queried for trends / BMIQ / cohort — the promoted, indexed set.
METRIC_COLUMNS: tuple[str, ...] = tuple(s.column for s in _SPECS)

# Vendor/abbreviation aliases → canonical key.
ALIASES: dict[str, str] = {
    "smm": "skeletal_muscle_mass",
    "pbf": "percent_body_fat",
    "body_fat_percentage": "percent_body_fat",
    "body_fat_percent": "percent_body_fat",
    "bfm": "body_fat_mass",
    "ffm": "fat_free_mass",
    "slm": "soft_lean_mass",
    "bcm": "body_cell_mass",
    "bmc": "bone_mineral_content",
    "tbw": "total_body_water",
    "icw": "intracellular_water",
    "ecw": "extracellular_water",
    "ecw_ratio": "ecw_tbw_ratio",
    "ecw_tbw": "ecw_tbw_ratio",
    "bmr": "basal_metabolic_rate",
    "whr": "waist_hip_ratio",
    "waist": "waist_circumference",
    "hip": "hip_circumference",
    "phase_angle": "whole_body_phase_angle",
    "smi": "skeletal_muscle_index",
    "vfa": "visceral_fat_area",
    "vfl": "visceral_fat_level",
    "visceral_fat": "visceral_fat_level",
    "score": "device_score",
    "inbody_score": "device_score",
}

# Canonical keys BMIQ reads, grouped by dimension — used to feed patient_state.
BMIQ_KEYS: dict[BmiqDimension, list[str]] = {}
for _s in _SPECS:
    if _s.bmiq:
        BMIQ_KEYS.setdefault(_s.bmiq, []).append(_s.key)


def canonical_key(raw: str) -> str:
    """Normalize a raw/vendor key to its canonical form (may be non-canonical)."""
    key = raw.strip().lower().replace("-", "_").replace(" ", "_")
    return ALIASES.get(key, key)


def convert_to_canonical_unit(spec: MetricSpec, value: float, unit: str | None) -> tuple[float, str]:
    """Return (value, unit) in the metric's canonical unit, converting lb→kg / in→cm."""
    u = (unit or "").strip().lower()
    if spec.kind is MetricKind.MASS and u in {"lb", "lbs", "pound", "pounds"}:
        return round(value * LB_TO_KG, 4), "kg"
    if spec.kind is MetricKind.LENGTH and u in {"in", "inch", "inches", '"'}:
        return round(value * IN_TO_CM, 4), "cm"
    return value, unit or spec.unit
