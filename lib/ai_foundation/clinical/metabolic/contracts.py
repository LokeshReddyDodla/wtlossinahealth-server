"""Typed contracts for the metabolic engine service boundary.

The engine internally uses plain dicts (pure stdlib). These Pydantic models
wrap the output at the service layer for type safety, validation, and
serialization. Agents consuming MetabolicService get typed objects.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Prediction(BaseModel):
    rise_mgdl: float
    predicted_mgdl: float
    observed_mgdl: float | None = None
    source: str                          # model:gbm | personal_slope
    confidence: str                      # high | moderate | cold-start
    n_meals_learned: int = 0
    personal_slope: float = 0.4


class Attribution(BaseModel):
    label: str                           # MEAL_DRIVEN | PHYSIOLOGY_DRIVEN | MIXED | IN_RANGE | INSUFFICIENT_HISTORY
    carb_component_mgdl: float = 0.0
    circadian_mgdl: float = 0.0
    residual_mgdl: float | None = None
    pre_term_mgdl: float = 0.0
    meal_fraction: float | None = None
    cgm_driver: str = "unknown"
    driver_consistent: bool | None = None
    recent_state: dict[str, Any] = Field(default_factory=dict)
    physiology_signal: str | None = None
    physiology_evidence: str | None = None


class PlateBalance(BaseModel):
    carb_ok: bool = False
    fiber_ok: bool = False
    protein_ok: bool = False
    cal_ok: bool = True
    balanced: bool = False
    slot_target_g: int = 50


class Lever(BaseModel):
    name: str
    say: str
    effect_mgdl: float
    cite: str
    model_config = {"extra": "allow"}


class Phenotype(BaseModel):
    tier: str | None = None
    agent_tone: str | None = None
    clinical_note: str | None = None
    escalation_threshold: str | float | None = None


class V31Enrichment(BaseModel):
    safety_unchecked: bool = False
    safety_note: str | None = None
    pre_prior: dict[str, Any] | None = None
    peak_minutes: int = 60
    peak_minutes_basis: str = "heuristic"
    evidence_meals: list[dict[str, Any]] = Field(default_factory=list)
    has_cgm: bool = False
    confidence_tier: str = "cold_start"
    show_number_to_patient: bool = False


class LensesResult(BaseModel):
    overnight_gv: dict[str, Any] = Field(default_factory=dict)
    hepatic_dawn: dict[str, Any] = Field(default_factory=dict)
    ir_phenotype: dict[str, Any] = Field(default_factory=dict)
    day_burden: dict[str, Any] = Field(default_factory=dict)
    people_like_you: dict[str, Any] = Field(default_factory=dict)
    model_config = {"extra": "allow"}


class EngineContract(BaseModel):
    """The full engine output — typed at the service boundary."""
    prediction: Prediction
    attribution: Attribution
    patient_flags: dict[str, Any] = Field(default_factory=dict)
    plate: PlateBalance
    lever: Lever | None = None
    phenotype: Phenotype
    output_mode: str                     # SUGGEST | REINFORCE | FLAG_PHYSIOLOGY | STATE_FACTS | SAFETY
    referral: str | None = None          # diet_team | care_team | None
    safety_flags: list[str] = Field(default_factory=list)
    bmiq: dict[str, Any] | None = None
    weight_trend: dict[str, Any] | None = None
    fact: str = ""
    restraint_cite: str = ""
    v31: V31Enrichment = Field(default_factory=V31Enrichment)
    lenses: LensesResult = Field(default_factory=LensesResult)

    model_config = {"extra": "allow"}
