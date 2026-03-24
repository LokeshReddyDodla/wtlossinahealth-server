"""
Fact Extractor — LLM-based patient fact extraction from every message.

Runs in the background (asyncio.ensure_future) so it never blocks the
response. The LLM decides whether facts exist — no hardcoded keywords.
Cost: ~$0.0002 per call (classification model). Worth it to never miss a fact.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


class PatientFact(BaseModel):
    key: str
    value: str


class ExtractedFacts(BaseModel):
    facts: list[PatientFact] = Field(default_factory=list)
    has_facts: bool = False


class FactExtractor:
    """Extracts and persists patient facts via LLM. Runs on every message in background."""

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
        """Extract facts from the message. Always runs — LLM decides if facts exist.

        This is called via asyncio.ensure_future so it never blocks the response.
        """
        if not self._memory or not self._gateway or not patient_id:
            return

        try:
            from lib.ai_foundation.models.registry import ModelTask

            result, _ = await self._gateway.extract(
                messages=[
                    {"role": "system", "content": (
                        "Extract ALL durable patient facts from the user's message. "
                        "Facts include: goals, weight, dietary preferences, allergies, "
                        "body notes, medical conditions, medications, fasting context, "
                        "activity preferences, communication style, or any personal health detail. "
                        "Set has_facts=true if ANY facts are found. "
                        "Set has_facts=false if the message is just a data query with no personal facts."
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
