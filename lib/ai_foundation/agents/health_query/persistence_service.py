"""
Persistence Service — all post-response operations.

Saves conversation turns, compacts threads (non-blocking), generates titles,
and records implicit feedback signals.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.models.gateway import ModelGateway
    from lib.ai_foundation.models.registry import ModelTask
    from lib.ai_foundation.agents.state import AgentInput
    from lib.ai_foundation.agents.health_query.contracts import QueryIntent

logger = logging.getLogger(__name__)


class PersistenceService:
    """Handles all post-response persistence: turns, compaction, titles, signals."""

    def __init__(
        self,
        *,
        memory: MemoryStore | None = None,
        gateway: ModelGateway | None = None,
    ) -> None:
        self._memory = memory
        self._gateway = gateway

    # -- Turn persistence --------------------------------------------------

    async def save_turn(
        self,
        *,
        thread_id: str | None,
        user_message: str,
        assistant_message: str,
        agent_id: str,
        intent_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Save user + assistant turns to the memory store."""
        if not self._memory or not thread_id:
            return

        from lib.ai_foundation.memory.base import ConversationTurn

        try:
            await self._memory.append_turn(
                thread_id,
                ConversationTurn(role="user", content=user_message, agent_id=agent_id),
            )
            await self._memory.append_turn(
                thread_id,
                ConversationTurn(
                    role="assistant", content=assistant_message,
                    agent_id=agent_id, metadata=intent_metadata or {},
                ),
            )
        except Exception as exc:
            logger.warning("Failed to persist turns: %s", exc)

    # -- Thread compaction (non-blocking) ----------------------------------

    async def compact_if_needed(self, *, thread_id: str | None, agent_id: str = "") -> None:
        """Compact thread summary + generate title. Call via asyncio.create_task()."""
        if not self._memory or not self._gateway or not thread_id:
            return

        try:
            turns = await self._memory.get_thread_turns(thread_id, limit=30)
            turn_count = len(turns)
            existing = await self._memory.get_thread_summary(thread_id)

            # Generate title on turn 2 (first complete exchange)
            if turn_count >= 2 and (not existing or not existing.title):
                title = await self._generate_title(turns[:2])
                from lib.ai_foundation.memory.base import ThreadSummary
                summary = existing or ThreadSummary(thread_id=thread_id, summary="", turn_count=turn_count)
                summary.title = title
                summary.turn_count = turn_count
                await self._memory.save_thread_summary(thread_id, summary)
                existing = summary

            # Compact summary every 2 turns after turn 4
            if turn_count < 4 or turn_count % 2 != 0:
                return
            if existing and existing.turn_count >= turn_count - 1:
                return

            conv_text = "\n".join(f"{t.role}: {t.content[:200]}" for t in turns[-12:])

            from lib.ai_foundation.models.registry import ModelTask
            response = await self._gateway.complete(
                messages=[
                    {"role": "system", "content": (
                        "Summarize this health conversation in 2-3 sentences. "
                        "Include: topics discussed, time period, patient goals. Be concise."
                    )},
                    {"role": "user", "content": conv_text},
                ],
                task=ModelTask.SUMMARIZATION,
            )

            from lib.ai_foundation.memory.base import ThreadSummary
            title = existing.title if existing and existing.title else ""
            summary = ThreadSummary(
                thread_id=thread_id, title=title,
                summary=response.content, turn_count=turn_count,
            )
            await self._memory.save_thread_summary(thread_id, summary)
            logger.debug("Compacted thread %s (%d turns)", thread_id, turn_count)

        except Exception as exc:
            logger.debug("Compaction failed (non-blocking): %s", exc)

    # -- Implicit feedback signals -----------------------------------------

    async def record_implicit_signals(
        self,
        *,
        thread_id: str | None,
        current_is_ready: bool,
    ) -> None:
        """Detect clarification-after-ready and record as negative signal."""
        if not self._memory or not thread_id:
            return

        try:
            turns = await self._memory.get_thread_turns(thread_id, limit=4)
            if len(turns) < 3:
                return

            # Find previous assistant turn
            prev_assistant = None
            for t in reversed(turns[:-2]):
                if t.role == "assistant":
                    prev_assistant = t
                    break

            if not prev_assistant or not prev_assistant.metadata:
                return

            prev_was_ready = prev_assistant.metadata.get("is_ready", False)
            prev_trace_id = prev_assistant.metadata.get("trace_id")

            if prev_was_ready and not current_is_ready and prev_trace_id:
                logger.debug("Implicit negative signal: clarification after is_ready=True")
                try:
                    from lib.ai_foundation.eval.collector import FinetuneDataCollector
                    from lib.core.container import container
                    collector: FinetuneDataCollector = container.resolve(FinetuneDataCollector)
                    await collector.add_implicit_signal(prev_trace_id, "user_asked_clarification_after", True)
                except Exception:
                    pass
        except Exception:
            pass

    # -- Title generation --------------------------------------------------

    async def _generate_title(self, first_turns: list) -> str:
        """Generate a short title from the first user message."""
        first_user_msg = ""
        for t in first_turns:
            if t.role == "user":
                first_user_msg = t.content
                break

        if not first_user_msg or not self._gateway:
            return first_user_msg[:50] + ("..." if len(first_user_msg) > 50 else "")

        try:
            from lib.ai_foundation.models.registry import ModelTask
            response = await self._gateway.complete(
                messages=[
                    {"role": "system", "content": (
                        "Generate a short title (3-8 words) for a health conversation "
                        "that starts with this message. Return ONLY the title."
                    )},
                    {"role": "user", "content": first_user_msg},
                ],
                task=ModelTask.CLASSIFICATION,
            )
            title = response.content.strip().strip('"').strip("'")
            return title[:60] + ("..." if len(title) > 60 else "")
        except Exception:
            return first_user_msg[:50] + ("..." if len(first_user_msg) > 50 else "")
