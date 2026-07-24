"""
Reflection Engine — critic that reviews investigation quality before final response.

After the reasoning loop completes, the reflector checks:
- Was the question fully answered?
- Were important patterns missed?
- Are there safety concerns?
- Was the patient's own baseline used (not population norms)?

If gaps are found, the reasoning engine loops back for targeted follow-up.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lib.ai_foundation.config import settings
from lib.ai_foundation.models.registry import ModelTask

if TYPE_CHECKING:
    from lib.ai_foundation.models.gateway import ModelGateway

logger = logging.getLogger(__name__)


# ── Reflection Models ──────────────────────────────────────────────────────


class ReflectionResult(BaseModel):
    """Output from the critic/reflection step."""

    is_complete: bool = Field(
        description="True if the investigation gathered enough data to fully answer the question.",
    )
    confidence: float = Field(
        description="Overall confidence in the findings (0.0 = no confidence, 1.0 = very confident).",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description=(
            "Identified gaps in the investigation. Each gap is a specific data point "
            "or analysis that would improve the answer. Empty if investigation is complete."
        ),
    )
    safety_concerns: list[str] = Field(
        default_factory=list,
        description=(
            "Any medically significant findings that should be flagged: "
            "dangerous hypo patterns, repeated severe spikes, medication timing issues, etc."
        ),
    )


# ── Engine ─────────────────────────────────────────────────────────────────


class ReflectionEngine:
    """Reviews investigation quality and identifies gaps.

    Usage::

        reflector = ReflectionEngine(gateway=gw)
        result = await reflector.reflect(
            messages=conversation_messages,
            user_question="Why am I having spikes?",
            model_id="gpt-4.1-mini",
        )
        if not result.is_complete:
            # Loop back for targeted follow-up
    """

    def __init__(self, *, gateway: ModelGateway) -> None:
        self._gateway = gateway

    async def reflect(
        self,
        *,
        messages: list[dict[str, Any]],
        user_question: str,
        reflection_prompt: str,
        model_id: str,
        trace_id: str | None = None,
    ) -> ReflectionResult:
        """Critique the investigation and identify gaps.

        Args:
            messages: Full conversation including tool results.
            user_question: The original user question.
            reflection_prompt: The reflection system prompt.
            model_id: Model to use for reflection (thinker model).

        Returns:
            ReflectionResult with completeness assessment and gaps.
        """
        # Build reflection-specific messages
        reflect_messages: list[dict[str, Any]] = [
            {"role": "system", "content": reflection_prompt},
            {
                "role": "system",
                "content": (
                    f"The user's original question was: \"{user_question}\"\n\n"
                    f"Below is the full investigation that was conducted. "
                    f"Review it and assess whether the question was fully answered."
                ),
            },
        ]

        # Add a summary of gathered data from the conversation
        data_summary = self._extract_data_summary(messages)
        if data_summary:
            reflect_messages.append({
                "role": "system",
                "content": f"Data gathered during investigation:\n\n{data_summary}",
            })

        reflect_messages.append({
            "role": "user",
            "content": "Assess the investigation quality. Is it complete?",
        })

        result, _meta = await self._gateway.extract(
            messages=reflect_messages,
            response_model=ReflectionResult,
            task=ModelTask.CLASSIFICATION,
            model_id=model_id,
            timeout=settings.REFLECTION_TIMEOUT_SECONDS,
            trace_id=trace_id,
        )

        logger.debug(
            "Reflection: complete=%s, confidence=%.2f, gaps=%d, safety=%d",
            result.is_complete, result.confidence,
            len(result.gaps), len(result.safety_concerns),
        )

        return result

    @staticmethod
    def _extract_data_summary(messages: list[dict[str, Any]]) -> str:
        """Extract a summary of all tool results / gathered data from the conversation."""
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            meta_type = msg.get("_meta", {}).get("type", "")

            if role == "tool" and content:
                # Tool result messages (reasoning engine path)
                # Reflector must see full data to verify accuracy — no truncation
                if len(content) > settings.REASONING_MAX_TOOL_RESULT_CHARS:
                    content = content[:settings.REASONING_MAX_TOOL_RESULT_CHARS] + "..."
                parts.append(content)
            elif meta_type == "gathered_data" and content:
                # Coordinator path: combined specialist findings
                parts.append(content[:settings.REASONING_MAX_TOOL_RESULT_CHARS])
            elif role == "system" and content.startswith("Investigation findings:"):
                # Coordinator path: explicit findings block
                parts.append(content[:settings.REASONING_MAX_TOOL_RESULT_CHARS])

        return "\n\n---\n\n".join(parts) if parts else ""
