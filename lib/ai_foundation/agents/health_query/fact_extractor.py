"""
Fact Extractor — conditional patient fact extraction from messages.

Only runs an LLM call when the message looks like it contains durable facts
(goals, weight, dietary preferences, etc.). Pure data queries like
"show meals today" skip the LLM call entirely.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)

# Keywords that suggest the message contains patient facts
_FACT_KEYWORDS = frozenset({
    "is", "am", "weighs", "weigh", "weight", "goal", "allergic", "allergy",
    "vegetarian", "vegan", "fasting", "note:", "remember", "preference",
    "intolerant", "intolerance", "condition", "diabetic", "medication",
    "metformin", "insulin", "pregnant", "smoking", "alcohol", "keto",
    "gluten", "lactose", "halal", "kosher", "ramadan",
})


class PatientFact(BaseModel):
    key: str
    value: str


class ExtractedFacts(BaseModel):
    facts: list[PatientFact] = Field(default_factory=list)
    has_facts: bool = False


class FactExtractor:
    """Extracts and persists patient facts — only when the message warrants it."""

    def __init__(
        self,
        *,
        memory: MemoryStore | None = None,
        gateway: ModelGateway | None = None,
    ) -> None:
        self._memory = memory
        self._gateway = gateway

    async def extract_if_needed(
        self,
        *,
        message: str,
        patient_id: str | None,
        agent_id: str = "health_query_v3",
    ) -> None:
        """Extract facts only if the message might contain them. Fire-and-forget."""
        if not self._memory or not self._gateway or not patient_id:
            return

        if not self._might_contain_facts(message):
            return

        try:
            from lib.ai_foundation.models.registry import ModelTask

            result, _ = await self._gateway.extract(
                messages=[
                    {"role": "system", "content": (
                        "Extract ALL durable patient facts from the user's message. "
                        "Facts include: goals, weight, dietary preferences, allergies, "
                        "body notes, medical conditions, medications, fasting context. "
                        "Set has_facts=true if ANY facts are found."
                    )},
                    {"role": "user", "content": message},
                ],
                response_model=ExtractedFacts,
                task=ModelTask.CLASSIFICATION,
            )

            if not result.has_facts or not result.facts:
                return

            from lib.ai_foundation.memory.base import MemoryFact

            facts = [
                MemoryFact(
                    key=f.key.strip(), value=f.value.strip(),
                    source="user", agent_id=agent_id, confidence=1.0,
                )
                for f in result.facts if f.key.strip() and f.value.strip()
            ]

            if facts:
                await self._memory.upsert_patient_facts(patient_id, facts)
                logger.debug("Persisted %d facts for patient", len(facts))

        except Exception as exc:
            logger.debug("Fact extraction failed (non-blocking): %s", exc)

    @staticmethod
    def _might_contain_facts(message: str) -> bool:
        """Quick keyword check — no LLM call if message is clearly just a data query."""
        words = set(message.lower().split())
        return bool(words & _FACT_KEYWORDS)
