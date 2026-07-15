"""
Fact Extractor — LLM-based patient memory extraction from every message.

Runs as a background task (spawned with a strong reference by the agent)
so it never blocks the response. The LLM decides whether memories exist — no hardcoded keywords.
Cost: ~$0.0002 per call (classification model). Worth it to never miss a fact.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from lib.ai_foundation.config import settings

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
    # Targets (mutable, numeric goals)
    "glucose_target_tir": {"category": "goal", "permanent": False},
    "weight_target": {"category": "goal", "permanent": False},
    "steps_target": {"category": "goal", "permanent": False},
    "sleep_target": {"category": "goal", "permanent": False},
    "calorie_target": {"category": "goal", "permanent": False},
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
    "Only extract facts the user actually states. NEVER carry a value from "
    "the examples below into your output — they show the input→output shape "
    "only. If the user did not mention an allergy, do not extract an allergy. "
    "If they did not mention a condition, do not extract a condition.\n\n"
    "Examples (shape only — substitute the user's actual words):\n"
    '- "I\'m [DIET_PREF]" → key: dietary_preference, value: [DIET_PREF]\n'
    '- "My goal is to lose [N] kg" → key: weight_goal, value: lose [N] kg\n'
    '- "I\'m allergic to [FOOD]" → key: food_allergy, value: [FOOD]\n'
    '- "I have [CONDITION]" → key: medical_condition (or diabetes_type ONLY for explicit diabetes mentions), value: [CONDITION]\n'
    '- "I [ACTIVITY] every [TIME]" → key: activity_preference, value: [ACTIVITY]\n'
    '- "Show me my meals" → no memories (this is a data query)\n\n'
    "CONVERSATIONAL ANSWERS: when an assistant message is provided as context, "
    "the user may be ANSWERING it. Resolve short replies against the assistant's "
    "question and store a SELF-CONTAINED fact — subject and meaning come from the "
    "question, value from the answer:\n"
    '- Assistant: "Did dinner run late on [DAY]?" / User: "yes, around [TIME]" '
    "→ key: meal_timing, value: sometimes eats dinner late (around [TIME])\n"
    '- Assistant: "Are you [DIET_PREF]?" / User: "yes" → key: dietary_preference, value: [DIET_PREF]\n'
    '- Assistant: "Are you [DIET_PREF]?" / User: "no" → NO fact (a denial is not a fact '
    "unless the user states an alternative)\n"
    "Never store a fact the user did not confirm. Acknowledgments and closers "
    '("ok", "thanks", "got it") contain no facts. If the user ignores the '
    "question and says something new, extract only from what they actually said.\n\n"
    "Set has_facts=true if ANY memories are found. "
    "Set has_facts=false if the message is just a data query with no personal facts."
)


def normalize_memory_key(raw: str) -> str:
    """Normalize a memory key: lowercase, underscores, stripped."""
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


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
        preceding_assistant_message: str | None = None,
    ) -> None:
        """Extract memories from the message. Always runs — LLM decides if facts exist.

        ``preceding_assistant_message`` is the agent's reply the user is
        responding to — without it, answers to the agent's own questions
        ("yes, around 1am") are contextless and evaporate. The companion
        flywheel depends on this parameter.

        Runs as an agent-spawned background task — never blocks the response.
        """
        if not self._memory or not self._gateway or not patient_id:
            return

        try:
            from lib.ai_foundation.models.registry import ModelTask

            if preceding_assistant_message:
                user_content = (
                    "Assistant's previous message (the user may be answering it):\n"
                    f"{preceding_assistant_message[:1500]}\n\n"
                    f"User's message:\n{message}"
                )
            else:
                user_content = message

            result, _ = await self._gateway.extract(
                messages=[
                    {"role": "system", "content": _EXTRACTION_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_model=ExtractedFacts,
                task=ModelTask.CLASSIFICATION,
            )

            if not result.has_facts or not result.facts:
                return

            from lib.ai_foundation.memory.base import MemoryFact, MemorySource

            facts = []
            for f in result.facts:
                key = normalize_memory_key(f.key)
                value = f.value.strip()
                if not key or not value:
                    continue
                # Guard against LLM generating excessively large memory values
                if len(value) > 1000:
                    logger.debug("Memory value too long (%d chars) for key %s, truncating", len(value), key)
                    value = value[:1000]

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
                # Observability for the "casual mention becomes permanent
                # allergy/condition" class of bug. Logs every permanent
                # fact with the originating user message so we can audit
                # whether passing references ("my sister has diabetes",
                # "I'm making eggs tomorrow") are being persisted as
                # patient facts. Grep `fact_extractor.permanent_fact`.
                for f in facts:
                    if f.is_permanent:
                        # DEBUG: the value + source message are PHI — keep the
                        # audit trail available (enable DEBUG to investigate
                        # the wrong-fact class of bug) without writing health
                        # content to INFO logs. Key alone stays at INFO.
                        logger.info(
                            "fact_extractor.permanent_fact | patient=%s key=%s",
                            patient_id[:8], f.key,
                        )
                        logger.debug(
                            "fact_extractor.permanent_fact.detail | value=%r source_msg=%r",
                            f.value, (message or "")[:200],
                        )
                await self._memory.upsert_patient_facts(patient_id, facts)
                logger.debug("Persisted %d memories for patient %s", len(facts), patient_id[:8])

            # Compact if memory is getting large
            await self._compact_if_needed(patient_id)

        except Exception as exc:
            logger.debug("Memory extraction failed (non-blocking): %s", exc)

    # -- Memory compaction --------------------------------------------------

    async def _compact_if_needed(self, patient_id: str) -> None:
        """Compact memories when they exceed the threshold.

        Strategy:
        - Group memories by category
        - For categories with > settings.COMPACT_KEEP_RECENT items:
          - Keep the N most recent as-is
          - Summarize the rest into one "summary" memory via LLM
          - Delete the old individual memories
        - Permanent memories are never compacted
        """
        if not self._memory or not self._gateway:
            return

        try:
            all_facts = await self._memory.get_patient_facts(patient_id)
            if len(all_facts) <= settings.COMPACT_THRESHOLD:
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
                if len(facts) <= settings.COMPACT_KEEP_RECENT:
                    continue

                # Split: keep recent, summarize old
                # Facts are sorted newest-first from get_patient_facts
                to_summarize = [
                    f for f in facts[settings.COMPACT_KEEP_RECENT:]
                    if not getattr(f, "is_permanent", False) and not f.key.endswith("_summary")
                ]

                if not to_summarize:
                    continue

                # Include the PREVIOUS summary in the input — the new summary
                # replaces it, so leaving it out would permanently drop
                # everything compacted in earlier cycles.
                prior_summary = next(
                    (f for f in facts if f.key == f"{cat}_summary"), None,
                )

                # Summarize old memories via LLM
                items_text = "\n".join(f"- {f.key}: {f.value}" for f in to_summarize)
                if prior_summary:
                    items_text = (
                        f"- earlier {cat} summary (merge this in): {prior_summary.value}\n"
                        + items_text
                    )
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

                    # Insert summary FIRST — if this fails, individual memories are preserved.
                    summary_fact = MemoryFact(
                        key=f"{cat}_summary",
                        value=response.content.strip(),
                        category=cat,
                        source=MemorySource.SYSTEM.value,
                        confidence=0.8,
                        is_permanent=False,
                    )
                    await self._memory.upsert_patient_facts(patient_id, [summary_fact])

                    # Delete old individual memories only after summary is
                    # safely persisted — one bulk delete, not N round trips.
                    deleted = await self._memory.delete_patient_facts(
                        patient_id, [f.key for f in to_summarize],
                    )
                    logger.info(
                        "Compacted %d %s memories → summary for %s (deleted %d)",
                        len(to_summarize), cat, patient_id[:8], deleted,
                    )

                except Exception as exc:
                    logger.debug("Compaction failed for category %s: %s", cat, exc)

        except Exception as exc:
            logger.debug("Memory compaction check failed: %s", exc)
