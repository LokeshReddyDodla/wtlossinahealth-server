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
from uuid import UUID
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lib.ai_foundation.config import settings
from lib.services.gamification.time_utils import local_now

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.agents.core.patient_resolver import PatientNameResolver
    from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
    from lib.services.gamification.service import GamificationService

logger = logging.getLogger(__name__)


class AgentContext(BaseModel):
    """All context loaded before the pipeline runs."""

    facts: list[dict] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    thread_summary: str | None = None
    patient_names: dict[str, str] = Field(default_factory=dict)
    recent_insights: list[dict] = Field(default_factory=list)
    local_time: str | None = None  # device local time for date resolution
    gamification: dict[str, Any] | None = None


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
        {"role": "system", "content": system_prompt, "_meta": {"type": "system_prompt"}},
        {"role": "system", "content": reasoning_prompt, "_meta": {"type": "instruction"}},
    ]

    # Pre-load patient context
    context_parts: list[str] = []
    if context.local_time:
        context_parts.append(
            f"User's local time: {context.local_time}. "
            f"Use THIS for resolving 'today', 'yesterday', 'this week', etc."
        )
    if context.patient_names:
        names = [f"- {pid}: {name}" for pid, name in context.patient_names.items()]
        context_parts.append("Patient names:\n" + "\n".join(names))
    if context.gamification:
        g = context.gamification
        context_parts.append(
            "Gamification:\n"
            f"- Level: {g.get('level', 1)} ({g.get('title', 'Newcomer')})\n"
            f"- Total XP: {g.get('total_xp', 0)}\n"
            f"- Current streak: {g.get('current_streak', 0)}\n"
            f"- Streak freezes: {g.get('streak_freezes', 0)}\n"
            f"- Recent achievements: {', '.join(g.get('recent_achievements', [])) or 'None'}\n"
            f"- Tasks today: {g.get('tasks_today', {}).get('completed', 0)}/{g.get('tasks_today', {}).get('total', 0)}\n"
            f"- Weekly quest: {g.get('weekly_quest') or 'None'}\n"
            f"- Active challenges: {g.get('active_challenges', [])}\n"
            f"- Buddy streak: {g.get('buddy_streak') or 0}"
        )

    if context_parts:
        messages.append({
            "role": "system",
            "content": "PATIENT CONTEXT (pre-loaded):\n\n" + "\n\n".join(context_parts),
            "_meta": {"type": "context"},
        })

    # Facts (separate message for pruning)
    if context.facts:
        by_category: dict[str, list[str]] = {}
        pinned_keys: list[str] = []
        for f in context.facts[:settings.MAX_CONTEXT_FACTS]:
            cat = f.get("category", "other")
            by_category.setdefault(cat, []).append(f"{f.get('key', 'unknown')}: {f.get('value', '')}")
            if f.get("is_permanent") or f.get("source") == "user_explicit":
                pinned_keys.append(f.get("key", ""))
        lines = ["Patient memories:"]
        for cat, items in by_category.items():
            lines.append(f"  {cat.title()}: {', '.join(items)}")
        messages.append({
            "role": "system",
            "content": "\n".join(lines),
            "_meta": {"type": "fact", "pinned_keys": pinned_keys},
        })

    # Thread summary
    if context.thread_summary:
        messages.append({
            "role": "system",
            "content": f"Conversation summary:\n{context.thread_summary}",
            "_meta": {"type": "summary"},
        })

    # Recent insights (separate for pruning)
    if context.recent_insights:
        lines = ["Recent health insights (notifications sent to this patient):"]
        for ins in context.recent_insights[:5]:
            lines.append(f"- [{ins.get('severity', '')}] {ins.get('title', '')}: {ins.get('message', '')}")
        messages.append({
            "role": "system",
            "content": "\n".join(lines),
            "_meta": {"type": "insight"},
        })

    # Add conversation history
    for msg in context.history[-settings.MAX_HISTORY_MESSAGES:]:
        tagged = {**msg, "_meta": {"type": "history"}}
        messages.append(tagged)

    # User's question
    messages.append({"role": "user", "content": user_message, "_meta": {"type": "user_question"}})

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
        insight_tracker: InsightTracker | None = None,
        gamification_service: GamificationService | None = None,
    ) -> None:
        self._memory = memory
        self._resolver = patient_resolver
        self._insight_tracker = insight_tracker
        self._gamification_service = gamification_service

    async def load(
        self,
        *,
        patient_id: str | None = None,
        patient_ids: list[str] | None = None,
        thread_id: str | None = None,
    ) -> AgentContext:
        """Load all context in parallel — 5 independent calls via asyncio.gather."""
        import asyncio

        facts_task = self._load_facts(patient_id)
        history_task = self._load_history(thread_id)
        summary_task = self._load_summary(thread_id)
        names_task = self._load_names(patient_ids or ([patient_id] if patient_id else []))
        insights_task = self._load_recent_insights(patient_id)
        gamification_task = self._load_gamification(patient_id)
        local_time_task = self._load_local_time(patient_id)

        facts, history, summary, names, insights, gamification, local_time = await asyncio.gather(
            facts_task,
            history_task,
            summary_task,
            names_task,
            insights_task,
            gamification_task,
            local_time_task,
        )

        return AgentContext(
            facts=facts,
            history=history,
            thread_summary=summary,
            patient_names=names,
            recent_insights=insights,
            gamification=gamification,
            local_time=local_time,
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

    async def _load_recent_insights(self, patient_id: str | None) -> list[dict]:
        if not self._insight_tracker or not patient_id:
            return []
        try:
            return await self._insight_tracker.get_history(patient_id, limit=5)
        except Exception as exc:
            logger.debug("Failed to load recent insights: %s", exc)
            return []

    async def _load_gamification(self, patient_id: str | None) -> dict[str, Any] | None:
        if not patient_id or not self._gamification_service:
            return None
        try:
            context = await self._gamification_service.get_gamification_context(
                UUID(patient_id)
            )
            return context.model_dump(mode="json")
        except Exception as exc:
            logger.debug("Failed to load gamification context: %s", exc)
            return None

    async def _load_local_time(self, patient_id: str | None) -> str | None:
        if not patient_id or not self._resolver:
            return None
        try:
            timezones = await self._resolver.resolve_timezones([patient_id])
            tz_name = timezones.get(patient_id)
            return local_now(tz_name).strftime("%Y-%m-%d %H:%M %Z")
        except Exception as exc:
            logger.debug("Failed to load local time: %s", exc)
            return None
