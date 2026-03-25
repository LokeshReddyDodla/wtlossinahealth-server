"""
Context Loader — loads all context needed before the agent pipeline runs.

Resolves patient facts, conversation history, thread summary, and patient
names in one call. Everything the agent needs to build LLM messages.

Also provides ``build_context_messages`` — the single place that turns an
AgentContext into the initial LLM message array used by both the
ReasoningEngine and the Coordinator.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lib.ai_foundation.config import settings

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.agents.health_query.patient_resolver import PatientNameResolver

logger = logging.getLogger(__name__)


class AgentContext(BaseModel):
    """All context loaded before the pipeline runs."""

    facts: list[dict] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    thread_summary: str | None = None
    patient_names: dict[str, str] = Field(default_factory=dict)


def build_context_messages(
    *,
    user_message: str,
    system_prompt: str,
    reasoning_prompt: str,
    context: AgentContext,
) -> list[dict[str, Any]]:
    """Build the initial LLM message array from patient context.

    Shared by both :class:`ReasoningEngine` and :class:`Coordinator` so the
    message structure stays consistent.  Uses ``settings.MAX_CONTEXT_FACTS``
    and ``settings.MAX_HISTORY_MESSAGES`` for truncation.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": reasoning_prompt},
    ]

    # Pre-load patient context (profile + facts + names)
    context_parts: list[str] = []
    if context.patient_names:
        names = [f"- {pid}: {name}" for pid, name in context.patient_names.items()]
        context_parts.append("Patient names:\n" + "\n".join(names))
    if context.facts:
        facts = [
            f"- {f['key']}: {f['value']}"
            for f in context.facts[:settings.MAX_CONTEXT_FACTS]
        ]
        context_parts.append("Known patient facts:\n" + "\n".join(facts))
    if context.thread_summary:
        context_parts.append(f"Conversation summary:\n{context.thread_summary}")

    if context_parts:
        messages.append({
            "role": "system",
            "content": "PATIENT CONTEXT (pre-loaded):\n\n" + "\n\n".join(context_parts),
        })

    # Add conversation history
    messages.extend(context.history[-settings.MAX_HISTORY_MESSAGES:])

    # User's question
    messages.append({"role": "user", "content": user_message})

    return messages


class ContextLoader:
    """Loads patient facts, conversation history, thread summary, and names.

    One service, one call — replaces 4 separate methods on the agent.
    """

    def __init__(
        self,
        *,
        memory: MemoryStore | None = None,
        patient_resolver: PatientNameResolver | None = None,
    ) -> None:
        self._memory = memory
        self._resolver = patient_resolver

    async def load(
        self,
        *,
        patient_id: str | None = None,
        patient_ids: list[str] | None = None,
        thread_id: str | None = None,
    ) -> AgentContext:
        """Load all context in parallel — 4 independent calls via asyncio.gather."""
        import asyncio

        facts_task = self._load_facts(patient_id)
        history_task = self._load_history(thread_id)
        summary_task = self._load_summary(thread_id)
        names_task = self._load_names(patient_ids or ([patient_id] if patient_id else []))

        facts, history, summary, names = await asyncio.gather(
            facts_task, history_task, summary_task, names_task,
        )

        return AgentContext(
            facts=facts,
            history=history,
            thread_summary=summary,
            patient_names=names,
        )

    async def _load_facts(self, patient_id: str | None) -> list[dict]:
        if not self._memory or not patient_id:
            return []
        try:
            facts = await self._memory.get_patient_facts(patient_id)
            return [f.model_dump(mode="json") for f in facts]
        except Exception as exc:
            logger.debug("Failed to load patient facts: %s", exc)
            return []

    async def _load_history(self, thread_id: str | None) -> list[dict[str, str]]:
        if not self._memory or not thread_id:
            return []
        try:
            turns = await self._memory.get_thread_turns(thread_id, limit=10)
            return [{"role": t.role, "content": t.content} for t in turns]
        except Exception as exc:
            logger.debug("Failed to load history: %s", exc)
            return []

    async def _load_summary(self, thread_id: str | None) -> str | None:
        if not self._memory or not thread_id:
            return None
        try:
            summary = await self._memory.get_thread_summary(thread_id)
            return summary.summary if summary and summary.summary else None
        except Exception as exc:
            logger.debug("Failed to load thread summary: %s", exc)
            return None

    async def _load_names(self, patient_ids: list[str]) -> dict[str, str]:
        if not self._resolver or not patient_ids:
            return {}
        try:
            return await self._resolver.resolve_names(patient_ids)
        except Exception as exc:
            logger.debug("Failed to resolve patient names: %s", exc)
            return {pid: f"Patient ({pid[:8]})" for pid in patient_ids}
