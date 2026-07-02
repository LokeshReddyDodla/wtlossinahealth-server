"""Fixture context + agent assembly for meal-analysis evals.

Real: gateway, prompts, extractor/scorer/alternatives/predictor pipeline.
Fake: context loader (fixed patient context), retriever (no similar meals).
"""

from __future__ import annotations

from datetime import datetime

from lib.ai_foundation.agents.meal_analysis.agent import MealAnalysisAgent
from lib.ai_foundation.agents.meal_analysis.alternatives import AlternativesEngine
from lib.ai_foundation.agents.meal_analysis.context_loader import MealAnalysisContext
from lib.ai_foundation.agents.meal_analysis.extractor import MealExtractor
from lib.ai_foundation.agents.meal_analysis.glucose_predictor import GlucosePredictor
from lib.ai_foundation.agents.meal_analysis.scorer import MealScorer
from lib.ai_foundation.prompts.registry import PromptRegistry

from .agent_factory import shared_gateway
from .fixtures import FixtureRetriever

_MEAL_PROMPTS_DIR = (
    __import__("pathlib").Path(__file__).parent.parent
    / "lib" / "ai_foundation" / "agents" / "meal_analysis" / "prompts"
)


class FakeMealContextLoader:
    """Deterministic patient context: T2D, vegetarian-leaning, CGM user."""

    async def load(self, *, patient_id: str, local_now: datetime) -> MealAnalysisContext:
        return MealAnalysisContext(
            patient_id=patient_id,
            local_now=local_now,
            profile={
                "name": "Asha",
                "age": 42,
                "gender": "female",
                "condition": "type 2 diabetes (2022)",
                "dietary_preference": "vegetarian",
            },
            recent_meals=[],
            has_cgm=True,
            medications=[{"name": "Metformin", "dose": "500mg", "frequency": "twice daily"}],
        )


def build_meal_agent() -> MealAnalysisAgent:
    gateway = shared_gateway()
    prompts = PromptRegistry()
    prompts.register_directory(_MEAL_PROMPTS_DIR, namespace="meal_analysis")

    return MealAnalysisAgent(
        gateway=gateway,
        qdrant_retriever=FixtureRetriever([]),  # no similar-meal history
        context_loader=FakeMealContextLoader(),
        extractor=MealExtractor(gateway=gateway, prompt_registry=prompts),
        scorer=MealScorer(gateway=gateway, prompt_registry=prompts),
        alternatives=AlternativesEngine(gateway=gateway, prompt_registry=prompts),
        glucose_predictor=GlucosePredictor(gateway=gateway, prompt_registry=prompts),
        metabolic_service=None,
    )
