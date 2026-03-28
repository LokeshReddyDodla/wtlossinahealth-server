"""
Fact Extractor — LLM-based patient memory extraction from every message.

Runs in the background (asyncio.ensure_future) so it never blocks the
response. The LLM decides whether memories exist — no hardcoded keywords.
Cost: ~$0.0002 per call (classification model). Worth it to never miss a fact.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


# Canonical memory keys — the LLM should use these exact keys.
# Maps key → (category, is_permanent)
CANONICAL_MEMORY_KEYS: dict[str, dict] = {
    # Conditions (permanent)
    "diabetes_type": {"category": "condition", "permanent": True},
    "medical_condition": {"category": "condition", "permanent": True},
    "medication": {"category": "condition", "permanent": False},
    "food_allergy": {"category": "condition", "permanent": True},
    "drug_allergy": {"category": "condition", "permanent": True},
    # Goals (mutable)
    "health_goal": {"category": "goal", "permanent": False},
    "weight_goal": {"category": "goal", "permanent": False},
    # Preferences (mutable)
    "dietary_preference": {"category": "preference", "permanent": False},
    "cuisine_preference": {"category": "preference", "permanent": False},
    "meal_timing": {"category": "preference", "permanent": False},
    "activity_preference": {"category": "preference", "permanent": False},
    # Measurements (mutable)
    "weight": {"category": "health", "permanent": False},
    "height": {"category": "health", "permanent": True},
    # Lifestyle (mutable)
    "activity_level": {"category": "lifestyle", "permanent": False},
    "sleep_pattern": {"category": "lifestyle", "permanent": False},
    "fasting_context": {"category": "lifestyle", "permanent": False},
    "smoking_status": {"category": "lifestyle", "permanent": False},
    "alcohol_status": {"category": "lifestyle", "permanent": False},
}

_CANONICAL_KEYS_LIST = ", ".join(CANONICAL_MEMORY_KEYS.keys())

_EXTRACTION_PROMPT = (
    "Extract patient memories from the user's message. Memories are durable personal "
    "facts — NOT data queries or conversational filler.\n\n"
    f"Use these exact keys: {_CANONICAL_KEYS_LIST}\n"
    "If a fact doesn't fit any key, use a descriptive snake_case key.\n\n"
    "Examples:\n"
    '- "I\'m vegetarian" → key: dietary_preference, value: vegetarian\n'
    '- "My goal is to lose 5 kg" → key: weight_goal, value: lose 5 kg\n'
    '- "I\'m allergic to peanuts" → key: food_allergy, value: peanuts\n'
    '- "I have type 2 diabetes" → key: diabetes_type, value: type 2\n'
    '- "I walk every morning" → key: activity_preference, value: morning walks\n'
    '- "Show me my meals" → no memories (this is a data query)\n\n'
    "Set has_facts=true if ANY memories are found. "
    "Set has_facts=false if the message is just a data query with no personal facts."
)


class ExtractedFact(BaseModel):
    key: str
    value: str


class ExtractedFacts(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)
    has_facts: bool = False


class FactExtractor:
    """Extracts and persists patient memories via LLM. Runs on every message in background."""

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
        """Extract memories from the message. Always runs — LLM decides if facts exist.

        This is called via asyncio.ensure_future so it never blocks the response.
        """
        if not self._memory or not self._gateway or not patient_id:
            return

        try:
            from lib.ai_foundation.models.registry import ModelTask

            result, _ = await self._gateway.extract(
                messages=[
                    {"role": "system", "content": _EXTRACTION_PROMPT},
                    {"role": "user", "content": message},
                ],
                response_model=ExtractedFacts,
                task=ModelTask.CLASSIFICATION,
            )

            if not result.has_facts or not result.facts:
                return

            from lib.ai_foundation.memory.base import MemoryFact, MemorySource

            facts = []
            for f in result.facts:
                key = f.key.strip().lower().replace(" ", "_").replace("-", "_")
                value = f.value.strip()
                if not key or not value:
                    continue

                # Look up canonical metadata
                meta = CANONICAL_MEMORY_KEYS.get(key, {"category": "other", "permanent": False})

                facts.append(MemoryFact(
                    key=key,
                    value=value,
                    category=meta["category"],
                    source=MemorySource.AUTO_EXTRACTED.value,
                    agent_id=agent_id,
                    confidence=0.9,  # auto-extracted = slightly less than user-explicit
                    is_permanent=meta["permanent"],
                ))

            if facts:
                await self._memory.upsert_patient_facts(patient_id, facts)
                logger.debug("Persisted %d memories for patient %s", len(facts), patient_id[:8])

            # Compact if memory is getting large
            await self._compact_if_needed(patient_id)

        except Exception as exc:
            logger.debug("Memory extraction failed (non-blocking): %s", exc)

    # -- Memory compaction --------------------------------------------------

    _COMPACT_THRESHOLD = 50
    _KEEP_RECENT_PER_CATEGORY = 5

    async def _compact_if_needed(self, patient_id: str) -> None:
        """Compact memories when they exceed the threshold.

        Strategy:
        - Group memories by category
        - For categories with > _KEEP_RECENT_PER_CATEGORY items:
          - Keep the N most recent as-is
          - Summarize the rest into one "summary" memory via LLM
          - Delete the old individual memories
        - Permanent memories are never compacted
        """
        if not self._memory or not self._gateway:
            return

        try:
            all_facts = await self._memory.get_patient_facts(patient_id)
            if len(all_facts) <= self._COMPACT_THRESHOLD:
                return

            logger.info("Compacting memories for %s: %d items", patient_id[:8], len(all_facts))

            # Group by category
            by_cat: dict[str, list] = {}
            for f in all_facts:
                cat = getattr(f, "category", "other") or "other"
                by_cat.setdefault(cat, []).append(f)

            from lib.ai_foundation.memory.base import MemoryFact, MemorySource
            from lib.ai_foundation.models.registry import ModelTask

            for cat, facts in by_cat.items():
                if len(facts) <= self._KEEP_RECENT_PER_CATEGORY:
                    continue

                # Split: keep recent, summarize old
                # Facts are sorted newest-first from get_patient_facts
                to_summarize = [
                    f for f in facts[self._KEEP_RECENT_PER_CATEGORY:]
                    if not getattr(f, "is_permanent", False) and not f.key.endswith("_summary")
                ]

                if not to_summarize:
                    continue

                # Summarize old memories via LLM
                items_text = "\n".join(f"- {f.key}: {f.value}" for f in to_summarize)
                try:
                    response = await self._gateway.complete(
                        messages=[
                            {"role": "system", "content": (
                                f"Summarize these {cat} memories into one concise sentence. "
                                "Keep all important details. Return ONLY the summary."
                            )},
                            {"role": "user", "content": items_text},
                        ],
                        task=ModelTask.SUMMARIZATION,
                    )

                    # Delete old individual memories concurrently.
                    # These are independent I/O calls and order does not matter.
                    delete_tasks = [
                        self._memory.delete_patient_fact(patient_id, f.key)
                        for f in to_summarize
                    ]
                    await asyncio.gather(*delete_tasks, return_exceptions=True)

                    # Insert summary memory
                    summary_fact = MemoryFact(
                        key=f"{cat}_summary",
                        value=response.content.strip(),
                        category=cat,
                        source=MemorySource.SYSTEM.value,
                        confidence=0.8,
                        is_permanent=False,
                    )
                    await self._memory.upsert_patient_facts(patient_id, [summary_fact])
                    logger.info("Compacted %d %s memories → summary for %s", len(to_summarize), cat, patient_id[:8])

                except Exception as exc:
                    logger.debug("Compaction failed for category %s: %s", cat, exc)

        except Exception as exc:
            logger.debug("Memory compaction check failed: %s", exc)
