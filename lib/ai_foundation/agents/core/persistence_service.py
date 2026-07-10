"""
Persistence Service — all post-response operations.

Saves conversation turns, compacts threads (non-blocking), generates titles,
and records implicit feedback signals.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from lib.ai_foundation.config import settings
from lib.ai_foundation.memory.base import ConversationTurn, ThreadSummary
from lib.ai_foundation.models.registry import ModelTask

if TYPE_CHECKING:
    from lib.ai_foundation.memory.base import MemoryStore
    from lib.ai_foundation.models.gateway import ModelGateway
    from lib.ai_foundation.agents.state import AgentInput

logger = logging.getLogger(__name__)


class ThreadDigest(BaseModel):
    """Structured compaction output — populates ThreadSummary continuity fields."""

    summary: str
    goal: str | None = None
    domains: list[str] = []
    date_scope: str | None = None


class PersistenceService:
    """Handles all post-response persistence: turns, compaction, titles, signals."""

    def __init__(
        self,
        *,
        memory: MemoryStore | None = None,
        gateway: ModelGateway | None = None,
        cache_store: Any | None = None,
    ) -> None:
        self._memory = memory
        self._gateway = gateway
        self._cache = cache_store  # CacheStore for distributed Redis lock
        self._compacting: set[str] = set()  # in-memory fast path (single-process)

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
    ) -> Any | None:
        """Save user + assistant turns to the memory store.

        Returns the assistant turn's Mongo id (or None on failure) so late
        metadata (the async English audit copy) can target exactly this turn.

        Args:
            user_timestamp: When the user sent the message (captured at pipeline start).
                            If None, uses current time for both turns.
        """
        if not self._memory or not thread_id:
            return None

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

            meta = intent_metadata or {}
            user_meta = {}
            if meta.get("channel"):
                user_meta["channel"] = meta["channel"]
            if meta.get("input_mode"):
                user_meta["input_mode"] = meta["input_mode"]

            user_turn = ConversationTurn(
                role="user", content=user_message,
                agent_id=agent_id, metadata=user_meta,
                timestamp=user_ts,
            )
            assistant_turn = ConversationTurn(
                role="assistant", content=assistant_message,
                agent_id=agent_id, metadata=meta,
                timestamp=assistant_ts,
            )

            inserted = await self._memory.append_turns_batch(
                thread_id, [user_turn, assistant_turn]
            )
            await self._update_thread_state(thread_id, assistant_message)
            return inserted[-1] if inserted else None
        except Exception as exc:
            logger.warning("Failed to persist turns (thread=%s): %s", thread_id, exc)
            return None

    async def attach_translation(
        self, *, turn_id: Any, language: str, translations: dict[str, str],
        en_bubbles: list[str] | None = None,
    ) -> None:
        """Attach translation copies to a SPECIFIC assistant turn by id.

        Targeted by id, never "the latest turn" — a fast follow-up message or
        a proactive continuation can land a newer turn before this background
        translation finishes, and the copy must not attach to that one.

        ``language`` = what the user saw (turn content's language);
        ``translations`` = other-language copies, e.g. {"en": ...} audit copy;
        ``en_bubbles`` = the English copy split per bubble (same order as
        metadata.bubbles) so the app can toggle each bubble independently.
        """
        if not self._memory or turn_id is None:
            return
        try:
            patch: dict[str, Any] = {"language": language, "translations": translations}
            if en_bubbles:
                patch["en_bubbles"] = en_bubbles
            await self._memory.update_turn_metadata_by_id(turn_id, patch)
        except Exception as exc:
            logger.warning("Failed to attach translation (turn=%s): %s", turn_id, exc)

    PENDING_REQUEST_TTL_HOURS = 24

    async def record_pending_request(self, thread_id: str | None, entity_type: str) -> None:
        """The agent asked the user to log ``entity_type`` — remember it so the
        eventual log event can continue this conversation (companion Phase 3).

        Partial $set — the summary doc is shared with save_turn's state
        update and compaction, which run concurrently in the same
        post-response burst.
        """
        if not self._memory or not thread_id:
            return
        try:
            from datetime import timedelta

            now = datetime.now(timezone.utc)
            await self._memory.update_thread_summary_fields(thread_id, {
                "pending_data_request": {
                    "entity_type": entity_type,
                    "asked_at": now.isoformat(),
                    "expires_at": (now + timedelta(hours=self.PENDING_REQUEST_TTL_HOURS)).isoformat(),
                },
            })
        except Exception as exc:
            logger.debug("pending-request record failed (thread=%s): %s", thread_id, exc)

    @staticmethod
    def extract_open_question(assistant_message: str) -> str | None:
        """The last question the agent asked in its reply, if any.

        Takes the final '?'-terminated sentence outside code fences; a reply
        with no question returns None (clears the stored state).
        """
        if not assistant_message or "?" not in assistant_message:
            return None
        # drop code fences — '?' inside charts/code is not a question
        parts = assistant_message.split("```")
        prose = " ".join(parts[::2])
        # last '?'-terminated sentence: take text after the last sentence
        # break. '।' is the Hindi/Devanagari full stop and counts as a
        # sentence break like '. ' and '! '.
        last = None
        for chunk in prose.split("?")[:-1]:
            sent = chunk
            for sep in (". ", "! ", "। "):
                sent = sent.split(sep)[-1]
            sent = sent.strip().lstrip("-*# ")
            if sent:
                last = sent[-300:] + "?"
        return last

    async def _update_thread_state(self, thread_id: str, assistant_message: str) -> None:
        """Persist conversational micro-state (open question) on the summary doc.

        Partial $set — the summary doc is shared with the pending-request
        recorder, compaction, and the event-scan consumer; each writer may
        touch only the fields it owns.
        """
        try:
            question = self.extract_open_question(assistant_message)
            await self._memory.update_thread_summary_fields(
                thread_id, {"last_assistant_question": question},
            )
        except Exception as exc:
            logger.debug("thread-state update failed (thread=%s): %s", thread_id, exc)

    # -- Thread compaction (non-blocking) ----------------------------------

    async def compact_if_needed(self, *, thread_id: str | None, agent_id: str = "", patient_ids: list[str] | None = None) -> None:
        """Compact thread summary + generate title. Call via asyncio.create_task()."""
        if not self._memory or not self._gateway or not thread_id:
            return

        # Prevent concurrent compaction — in-memory fast path + distributed Redis lock
        if thread_id in self._compacting:
            logger.debug("Skipping compaction for %s — already in progress (local)", thread_id)
            return

        # Distributed lock via Redis SET NX (multi-instance safe)
        lock_key = f"compaction:lock:{thread_id}"
        if self._cache:
            try:
                # TTL = 2x task timeout so lock outlives the task even under slow LLM calls
                lock_ttl = int(settings.BACKGROUND_TASK_TIMEOUT_SECONDS * 2)
                acquired = self._cache.set_key(lock_key, "1", expire=lock_ttl, nx=True)
                if not acquired:
                    logger.debug("Skipping compaction for %s — locked by another instance", thread_id)
                    return
            except Exception as exc:
                logger.debug("Redis lock unavailable, falling back to local lock: %s", exc)

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
                title_fields: dict = {"title": title}
                if patient_ids:
                    title_fields["patient_ids"] = patient_ids
                await self._memory.update_thread_summary_fields(thread_id, title_fields)
                if existing:
                    existing.title = title
                else:
                    existing = ThreadSummary(
                        thread_id=thread_id, summary="", turn_count=turn_count, title=title,
                    )

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

            digest, _ = await self._gateway.extract(
                messages=[
                    {"role": "system", "content": (
                        "Digest this health conversation.\n"
                        "- summary: 2-3 sentences — topics discussed, time period, key findings.\n"
                        "- goal: the patient's active goal IF one is stated or clearly implied "
                        "(e.g. 'lose 5 kg', 'improve overnight glucose'); null otherwise.\n"
                        "- domains: health domains actively discussed "
                        "(e.g. glucose, meals, sleep, fitness, weight, medications).\n"
                        "- date_scope: the time period currently in focus "
                        "(e.g. 'this_week', 'last_month'); null if unclear."
                    )},
                    {"role": "user", "content": conv_text},
                ],
                response_model=ThreadDigest,
                task=ModelTask.SUMMARIZATION,
            )

            # Partial $set of ONLY compaction-owned fields — micro-state
            # (pending_data_request, last_assistant_question) belongs to
            # writers that run concurrently with the multi-second LLM call
            # above.
            digest_fields: dict = {
                "summary": digest.summary, "turn_count": turn_count,
                "goal": digest.goal, "domains": digest.domains,
                "date_scope": digest.date_scope,
            }
            if patient_ids:
                digest_fields["patient_ids"] = patient_ids
            await self._memory.update_thread_summary_fields(thread_id, digest_fields)
            elapsed_ms = int((_time.perf_counter() - start) * 1000)
            logger.info("Compacted thread %s (%d turns, %dms)", thread_id, turn_count, elapsed_ms)

        except Exception as exc:
            logger.warning("Compaction failed (thread=%s): %s", thread_id, exc)
        finally:
            self._compacting.discard(thread_id)
            if self._cache:
                try:
                    self._cache.delete_key(lock_key)
                except Exception:
                    pass  # TTL will clean up

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
