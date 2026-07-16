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
from datetime import datetime, timedelta, timezone
from uuid import UUID
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from lib.ai_foundation.config import settings
from lib.ai_foundation.agents.core.refs import Ref, ResolvedRef, resolve_refs
from lib.core.types import DEFAULT_AI_LANGUAGE
from lib.services.gamification.time_utils import local_now

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.retrieval.qdrant import QdrantRetriever
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
    pinned_refs: list[ResolvedRef] = Field(default_factory=list)
    local_time: str | None = None  # device local time for date resolution
    response_language: str = "en"  # patient's preferred AI language
    # Active provider-authored guidance (attributed dicts from CareIntentService)
    care_intents: list[dict] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}
    gamification: dict[str, Any] | None = None
    medications_text: str | None = None  # all medications (active + past) from Qdrant
    # Panel (multi-patient) mode — keyed by patient_id
    panel_facts: dict[str, list[dict]] = Field(default_factory=dict)
    panel_insights: dict[str, list[dict]] = Field(default_factory=dict)


def _recent_date_reference(local_time: str, days: int = 8) -> str | None:
    """Map recent calendar dates to weekday names, anchored on the date in
    ``local_time``. The responder computes weekdays from ISO dates unreliably
    (consistently off by one), so it must COPY these pairings, not derive them.
    Anchored on the same date the agent is told is 'today', so the map can't
    disagree with it. Pure calendar arithmetic — timezone-free by construction.
    """
    try:
        anchor = datetime.strptime(local_time.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None
    lines = []
    for i in range(days):
        d = anchor - timedelta(days=i)
        tag = " (today)" if i == 0 else " (yesterday)" if i == 1 else ""
        lines.append(f"- {d.isoformat()} = {d.strftime('%A')}{tag}")
    return "\n".join(lines)


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
        date_ref = _recent_date_reference(context.local_time)
        if date_ref:
            context_parts.append(
                "Exact date↔weekday pairings for recent days (COPY these when you "
                "name a weekday — never compute a weekday from a date yourself):\n"
                + date_ref
            )
    if context.patient_names:
        names = [f"- {pid}: {name}" for pid, name in context.patient_names.items()]
        context_parts.append("Patient names:\n" + "\n".join(names))

    # Panel coverage instruction — injected once, seen by every LLM in the pipeline
    if len(context.patient_names) > 1:
        patient_name_list = list(context.patient_names.values())
        context_parts.append(
            f"PANEL QUERY — you are analyzing {len(patient_name_list)} patients: "
            f"{', '.join(patient_name_list)}. "
            f"Your response MUST address each patient by name. "
            f"Do not focus on one patient and ignore the others. "
            f"Use each patient's first name as a sub-heading or clearly label their data."
        )
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

    if context.medications_text:
        context_parts.append(f"Patient Medications:\n{context.medications_text}")

    if context.care_intents:
        lines = []
        for ci in context.care_intents:
            cond = f" (when: {ci['trigger_condition']})" if ci.get("trigger_condition") else ""
            lines.append(f"- [{ci['author_name']}, {ci['author_role']}] {ci['original_text']}{cond}")
        context_parts.append(
            "CARE TEAM FOCUS — instructions this patient's providers gave for their care. "
            "When your answer touches one of these, reinforce it and attribute the provider "
            "by name (\"Dr. Mehta asked you to...\"). You are the patient's companion: "
            "acknowledge the care team's guidance, never police the patient with it, and "
            "NEVER invent an instruction that is not listed:\n" + "\n".join(lines)
        )

    if context_parts:
        messages.append({
            "role": "system",
            "content": "PATIENT CONTEXT (pre-loaded):\n\n" + "\n\n".join(context_parts),
            "_meta": {"type": "context"},
        })

    # Facts (separate message for pruning)
    if context.panel_facts:
        # Panel mode: per-patient facts grouped by patient name
        pnames = context.patient_names
        lines = ["Patient memories (by patient):"]
        pinned_keys: list[str] = []
        for pid, facts in context.panel_facts.items():
            if not facts:
                continue
            name = pnames.get(pid, f"Patient {pid[:8]}")
            by_cat: dict[str, list[str]] = {}
            for f in facts:
                cat = f.get("category", "other")
                by_cat.setdefault(cat, []).append(f"{f.get('key', '?')}: {f.get('value', '')}")
                if f.get("is_permanent") or f.get("source") == "user_explicit":
                    pinned_keys.append(f.get("key", ""))
            cat_parts = " | ".join(
                f"{cat.title()}: {', '.join(items)}" for cat, items in by_cat.items()
            )
            lines.append(f"  [{name}] {cat_parts}")
        messages.append({
            "role": "system",
            "content": "\n".join(lines),
            "_meta": {"type": "fact", "pinned_keys": pinned_keys},
        })
    elif context.facts:
        # Single-patient mode: flat facts list
        by_category: dict[str, list[str]] = {}
        pinned_keys = []
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
    if context.panel_insights:
        # Panel mode: per-patient insights
        pnames = context.patient_names
        lines = ["Recent health insights (by patient):"]
        for pid, insights in context.panel_insights.items():
            if not insights:
                continue
            name = pnames.get(pid, f"Patient {pid[:8]}")
            for ins in insights[:5]:
                lines.append(
                    f"  [{name}] [{ins.get('severity', '')}] "
                    f"{ins.get('title', '')}: {ins.get('message', '')}"
                )
        messages.append({
            "role": "system",
            "content": "\n".join(lines),
            "_meta": {"type": "insight"},
        })
    elif context.recent_insights:
        lines = ["Recent health insights (notifications sent to this patient):"]
        for ins in context.recent_insights[:8]:
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

    # Pinned refs — injected last so they're the freshest context before the question.
    # One system message per ref so each is independently traceable / prunable.
    for ref in context.pinned_refs:
        lines = [
            f"USER REFERENCED THIS {ref.type.value.upper()}:",
            f"Title: {ref.title}",
        ]
        if ref.summary:
            lines.append(ref.summary)
        if ref.occurred_at:
            lines.append(f"Occurred: {ref.occurred_at}")
        lines.append(
            "\nThe user's question is specifically about this entity. "
            "Anchor your investigation to it."
        )
        messages.append({
            "role": "system",
            "content": "\n".join(lines),
            "_meta": {"type": "pinned_ref", "ref_type": ref.type.value, "ref_id": ref.id},
        })

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
        retriever: QdrantRetriever | None = None,
        care_intents: Any | None = None,
    ) -> None:
        self._memory = memory
        self._resolver = patient_resolver
        self._insight_tracker = insight_tracker
        self._gamification_service = gamification_service
        self._retriever = retriever
        # Duck-typed reader: get_active_context(patient_id) -> list[dict]
        self._care_intents = care_intents

    async def load(
        self,
        *,
        patient_id: str | None = None,
        patient_ids: list[str] | None = None,
        thread_id: str | None = None,
        refs: list[Ref] | None = None,
    ) -> AgentContext:
        """Load all context in parallel. Panel mode (>1 patient) loads per-patient facts/insights."""
        import asyncio

        all_pids = patient_ids or ([patient_id] if patient_id else [])
        is_panel = len(all_pids) > 1

        if is_panel:
            # Panel mode: load facts + insights for every patient; skip gamification + local_time
            names, history, summary, panel_facts, panel_insights = await asyncio.gather(
                self._load_names(all_pids),
                self._load_history(thread_id),
                self._load_summary(thread_id),
                self._load_panel_facts(all_pids),
                self._load_panel_insights(all_pids),
            )
            return AgentContext(
                facts=[],
                history=history,
                thread_summary=summary,
                patient_names=names,
                recent_insights=[],
                gamification=None,
                local_time=None,
                panel_facts=panel_facts,
                panel_insights=panel_insights,
            )

        # Single-patient mode: original behaviour
        facts, history, summary, names, insights, gamification, local_time, medications_text, pinned_refs, response_language, care_intents = await asyncio.gather(
            self._load_facts(patient_id),
            self._load_history(thread_id),
            self._load_summary(thread_id),
            self._load_names(all_pids),
            self._load_recent_insights(patient_id),
            self._load_gamification(patient_id),
            self._load_local_time(patient_id),
            self._load_medications(patient_id),
            self._load_pinned_refs(refs, patient_id),
            self._load_response_language(patient_id),
            self._load_care_intents(patient_id),
        )

        return AgentContext(
            facts=facts,
            history=history,
            thread_summary=summary,
            patient_names=names,
            recent_insights=insights,
            gamification=gamification,
            local_time=local_time,
            medications_text=medications_text,
            pinned_refs=pinned_refs,
            response_language=response_language,
            care_intents=care_intents,
        )

    async def _load_care_intents(self, patient_id: str | None) -> list[dict]:
        if not self._care_intents or not patient_id:
            return []
        try:
            return await self._care_intents.get_active_context(patient_id)
        except Exception as exc:
            logger.debug("Failed to load care intents: %s", exc)
            return []

    async def _load_facts(self, patient_id: str | None) -> list[dict]:
        if not self._memory or not patient_id:
            return []
        try:
            facts = await self._memory.get_patient_facts(patient_id)
            return [f.model_dump(mode="json") for f in facts]
        except Exception as exc:
            logger.debug("Failed to load patient facts: %s", exc)
            return []

    async def _load_medications(self, patient_id: str | None) -> str | None:
        """Load all medications from Qdrant (no date filter — persistent context)."""
        if not self._retriever or not patient_id:
            return None
        try:
            from lib.ai_foundation.retrieval.base import RetrievalRequest

            results = await self._retriever.retrieve_filtered(
                RetrievalRequest(
                    patient_ids=[patient_id],
                    data_types=["medication"],
                    limit=5,
                )
            )

            # Filter to medication only — the should-filter also returns profile
            for r in results:
                dt = r.data_type or r.payload.get("data_type")
                if dt == "medication":
                    text = r.payload.get("text_repr", "")
                    if text:
                        return text
        except Exception as exc:
            logger.debug("Failed to load medications: %s", exc)
        return None

    async def _load_history(self, thread_id: str | None) -> list[dict[str, str]]:
        if not self._memory or not thread_id:
            return []
        try:
            turns = await self._memory.get_thread_turns(thread_id, limit=settings.MAX_HISTORY_MESSAGES)
            return [{"role": t.role, "content": t.content} for t in turns]
        except Exception as exc:
            logger.debug("Failed to load history: %s", exc)
            return []

    async def _load_summary(self, thread_id: str | None) -> str | None:
        if not self._memory or not thread_id:
            return None
        try:
            summary = await self._memory.get_thread_summary(thread_id)
            if not summary:
                return None
            parts: list[str] = []
            if summary.summary:
                parts.append(summary.summary)
            if summary.goal:
                parts.append(f"Patient's active goal in this conversation: {summary.goal}")
            pending = summary.pending_data_request
            if pending:
                try:
                    not_expired = datetime.fromisoformat(pending["expires_at"]) > datetime.now(timezone.utc)
                except Exception:
                    not_expired = False
                if not_expired:
                    parts.append(
                        f"You asked the user to log their {pending['entity_type']} and are "
                        "waiting for it — you'll analyze it when it arrives. Don't re-ask; "
                        "if they mention having logged it, look it up."
                    )
            if summary.last_assistant_question:
                parts.append(
                    "Open question you asked in your last reply (if the user's "
                    f"message answers it, connect the two; if they ignored it, drop it — "
                    f"do not re-ask): {summary.last_assistant_question}"
                )
            return "\n".join(parts) if parts else None
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

    async def _load_pinned_refs(
        self, refs: list[Ref] | None, patient_id: str | None
    ) -> list[ResolvedRef]:
        if not refs or not patient_id:
            return []
        tz_name: str | None = None
        if self._resolver:
            try:
                timezones = await self._resolver.resolve_timezones([patient_id])
                tz_name = timezones.get(patient_id)
            except Exception as exc:
                logger.debug("Failed to resolve tz for pinned refs: %s", exc)
        try:
            return await resolve_refs(
                patient_id=patient_id,
                refs=refs,
                tz=tz_name,
                insight_tracker=self._insight_tracker,
            )
        except Exception as exc:
            logger.debug("Failed to resolve pinned refs: %s", exc)
            return []

    async def _load_response_language(self, patient_id: str | None) -> str:
        if not patient_id or not self._resolver:
            return DEFAULT_AI_LANGUAGE
        try:
            return await self._resolver.resolve_language(patient_id)
        except Exception as exc:
            logger.debug("Failed to resolve preferred AI language: %s", exc)
            return DEFAULT_AI_LANGUAGE

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

    async def _load_panel_facts(self, patient_ids: list[str]) -> dict[str, list[dict]]:
        """Load facts for every patient in a panel, keyed by patient_id."""
        if not self._memory or not patient_ids:
            return {}

        import asyncio

        async def _one(pid: str) -> tuple[str, list[dict]]:
            try:
                facts = await self._memory.get_patient_facts(pid)
                return pid, [f.model_dump(mode="json") for f in facts[:settings.MAX_CONTEXT_FACTS]]
            except Exception as exc:
                logger.debug("Failed to load facts for %s: %s", pid, exc)
                return pid, []

        results = await asyncio.gather(*[_one(pid) for pid in patient_ids])
        return {pid: facts for pid, facts in results if facts}

    async def _load_panel_insights(self, patient_ids: list[str]) -> dict[str, list[dict]]:
        """Load recent proactive insights for every patient in a panel, keyed by patient_id."""
        if not self._insight_tracker or not patient_ids:
            return {}

        import asyncio

        async def _one(pid: str) -> tuple[str, list[dict]]:
            try:
                insights = await self._insight_tracker.get_history(pid, limit=3)
                return pid, insights
            except Exception as exc:
                logger.debug("Failed to load insights for %s: %s", pid, exc)
                return pid, []

        results = await asyncio.gather(*[_one(pid) for pid in patient_ids])
        return {pid: insights for pid, insights in results if insights}

    async def _load_local_time(self, patient_id: str | None) -> str | None:
        if not patient_id or not self._resolver:
            return None
        try:
            timezones = await self._resolver.resolve_timezones([patient_id])
            tz_name = timezones.get(patient_id)
            return local_now(tz_name).strftime("%Y-%m-%d %H:%M (%A) %Z")
        except Exception as exc:
            logger.debug("Failed to load local time: %s", exc)
            return None
