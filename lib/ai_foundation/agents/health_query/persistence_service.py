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

from lib.ai_foundation.config import settings
from lib.ai_foundation.memory.base import ConversationTurn, ThreadSummary
from lib.ai_foundation.models.registry import ModelTask

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.models.gateway import ModelGateway
    from lib.ai_foundation.agents.state import AgentInput
    from lib.ai_foundation.agents.health_query.contracts import QueryIntent

logger = logging.getLogger(__name__)


class PersistenceService:
    """Handles all post-response persistence: turns, compaction, titles, signals."""

    _compacting: set[str] = set()  # in-memory lock to prevent concurrent compaction

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
        patient_ids: list[str] | None = None,
        intent_metadata: dict[str, Any] | None = None,
        user_timestamp: Any | None = None,
    ) -> None:
        """Save user + assistant turns to the memory store.

        Args:
            user_timestamp: When the user sent the message (captured at pipeline start).
                            If None, uses current time for both turns.
        """
        if not self._memory or not thread_id:
            return

        now = datetime.now(timezone.utc)
        user_ts = user_timestamp if user_timestamp else now
        assistant_ts = now  # always "now" — when the response was generated

        try:
            # Ensure thread summary exists with patient_ids (on first turn)
            if patient_ids:
                existing = await self._memory.get_thread_summary(thread_id)
                if not existing:
                    await self._memory.save_thread_summary(thread_id, ThreadSummary(
                        thread_id=thread_id,
                        patient_ids=patient_ids,
                        summary="",
                        turn_count=0,
                    ))
                elif not existing.patient_ids and patient_ids:
                    existing.patient_ids = patient_ids
                    await self._memory.save_thread_summary(thread_id, existing)

            user_turn = ConversationTurn(
                role="user", content=user_message,
                agent_id=agent_id, timestamp=user_ts,
            )
            assistant_turn = ConversationTurn(
                role="assistant", content=assistant_message,
                agent_id=agent_id, metadata=intent_metadata or {},
                timestamp=assistant_ts,
            )

            await self._memory.append_turns_batch(thread_id, [user_turn, assistant_turn])
        except Exception as exc:
            logger.warning("Failed to persist turns (thread=%s): %s", thread_id, exc)

    # -- Thread compaction (non-blocking) ----------------------------------

    async def compact_if_needed(self, *, thread_id: str | None, agent_id: str = "", patient_ids: list[str] | None = None) -> None:
        """Compact thread summary + generate title. Call via asyncio.create_task()."""
        if not self._memory or not self._gateway or not thread_id:
            return

        # Prevent concurrent compaction on the same thread
        if thread_id in self._compacting:
            logger.debug("Skipping compaction for %s — already in progress", thread_id)
            return

        self._compacting.add(thread_id)
        try:
            import time as _time
            start = _time.perf_counter()

            # Get real turn count + summary in parallel
            turn_count, existing = await asyncio.gather(
                self._memory.count_thread_turns(thread_id),
                self._memory.get_thread_summary(thread_id),
            )

            # Generate title from the first exchange (not most recent)
            if turn_count >= 2 and (not existing or not existing.title):
                first_turns = await self._memory.get_first_thread_turns(thread_id, limit=2)
                title = await self._generate_title(first_turns)
                summary = existing or ThreadSummary(thread_id=thread_id, summary="", turn_count=turn_count)
                summary.title = title
                if patient_ids:
                    summary.patient_ids = patient_ids
                await self._memory.save_thread_summary(thread_id, summary)
                existing = summary

            # Compact summary at configured intervals
            threshold = settings.COMPACTION_TRIGGER_THRESHOLD
            interval = settings.COMPACTION_TRIGGER_INTERVAL
            if turn_count < threshold or turn_count % interval != 0:
                return

            # Guard: don't re-compact if already done for this turn count
            if existing and existing.summary and existing.turn_count >= turn_count - 1:
                return

            turns_for_summary = await self._memory.get_thread_turns(thread_id, limit=settings.COMPACTION_HISTORY_WINDOW)
            conv_text = "\n".join(f"{t.role}: {t.content[:settings.SUMMARY_TRUNCATION_CHARS]}" for t in turns_for_summary)

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

            title = existing.title if existing and existing.title else ""
            pids = patient_ids or (existing.patient_ids if existing else [])
            summary = ThreadSummary(
                thread_id=thread_id, title=title, patient_ids=pids,
                summary=response.content, turn_count=turn_count,
            )
            await self._memory.save_thread_summary(thread_id, summary)
            elapsed_ms = int((_time.perf_counter() - start) * 1000)
            logger.info("Compacted thread %s (%d turns, %dms)", thread_id, turn_count, elapsed_ms)

        except Exception as exc:
            logger.warning("Compaction failed (thread=%s): %s", thread_id, exc)
        finally:
            self._compacting.discard(thread_id)

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
