"""
Support Assistant — AI first responder inside patient support tickets.

One structured LLM call per patient message returns a triage (category,
urgency, needs_human, staff summary) plus the reply text. A deterministic
policy layer then decides what the patient actually sees:

- self-serve category, no human needed  -> the model's reply
- anything needing a person             -> model's short ack + hold template
- medical question                      -> model's reply + care-team redirect
- emergency                             -> emergency template only

The templates are English canonical strings translated through the
TranslationService; the model writes its own reply natively in the patient's
language. The "brain" is two markdown files in ./knowledge, edited directly.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lib.ai_foundation.agents.base import BaseAgent
from lib.ai_foundation.agents.state import AgentInput, AgentOutput
from lib.ai_foundation.config import settings
from lib.ai_foundation.models.registry import ModelTask
from lib.core.types import DEFAULT_AI_LANGUAGE, ai_language_name

from .contracts import (
    SELF_SERVE_CATEGORIES,
    CareTeamContact,
    HandlingMode,
    SupportCategory,
    SupportSnapshot,
    SupportTriage,
    SupportUrgency,
)

logger = logging.getLogger(__name__)

_KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

# Canonical English copy. Everything the patient reads that the model did not
# write goes through these so wording stays identical across tickets.
HOLD_MESSAGE = (
    "I've noted this for the support team. They will reply here in this same "
    "chat and you'll get a notification when they do. There's no need to send "
    "the message again."
)
HOLD_MESSAGE_AFTER_FAILURE = (
    "Thanks for your message. I've passed it to the support team, and they "
    "will reply here in this same chat. You'll get a notification when they do."
)
MEDICAL_REDIRECT_WITH_CONTACT = (
    "For anything medical, your care team is the right place to ask. You can "
    "reach them here:"
)
MEDICAL_REDIRECT_NO_CONTACT = (
    "For anything medical, your care team is the right place to ask. You can "
    "message them from the chat section of the app."
)
EMERGENCY_MESSAGE = (
    "If this is an emergency, please call emergency services right now: 108 "
    "for an ambulance or 112 in India, or your local emergency number. Do not "
    "wait for a reply here."
)
EMERGENCY_FACILITY_LINE = "Your clinic's emergency phone:"
EMERGENCY_CARE_TEAM_LINE = "Your care team:"
EMERGENCY_FLAGGED = (
    "I've also flagged this ticket as urgent so the support team sees it first."
)
SNAPSHOT_UNAVAILABLE = "unavailable (could not be checked right now)"


def _load_brain() -> str:
    system_prompt = (_KNOWLEDGE_DIR / "system_prompt.md").read_text(encoding="utf-8")
    knowledge_base = (_KNOWLEDGE_DIR / "knowledge_base.md").read_text(encoding="utf-8")
    return (
        f"{system_prompt}\n\n"
        "# KNOWLEDGE BASE (your only source of truth about the app)\n\n"
        f"{knowledge_base}"
    )


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "never"
    return value.strftime("%d %b %Y, %H:%M")


def _contact_line(contact: CareTeamContact) -> str:
    parts = [contact.name]
    if contact.role:
        parts[0] = f"{contact.name} ({contact.role})"
    if contact.phone:
        parts.append(contact.phone)
    if contact.email:
        parts.append(contact.email)
    line = " — ".join(parts)
    if not contact.is_active:
        line += " [currently unavailable]"
    return line


def render_snapshot(snapshot: SupportSnapshot) -> str:
    """Deterministic English rendering of the patient snapshot for the prompt.

    Sections that failed to load are labelled unavailable so the model says
    "I couldn't check" instead of guessing.
    """
    errs = set(snapshot.lookup_errors)
    lines: list[str] = ["# PATIENT SNAPSHOT (live, read-only facts about this patient)"]

    if snapshot.patient_first_name:
        lines.append(f"- Patient first name: {snapshot.patient_first_name}")
    lines.append(f"- Profile timezone: {snapshot.timezone or 'not set'}")
    lines.append(f"- Preferred language: {ai_language_name(snapshot.language)}")

    lines.append("")
    lines.append("## Care team")
    if "care_team" in errs:
        lines.append(f"- {SNAPSHOT_UNAVAILABLE}")
    elif not snapshot.care_team:
        lines.append("- No care provider is assigned to this patient.")
    else:
        for c in snapshot.care_team:
            lines.append(f"- {_contact_line(c)}")
    if snapshot.facility:
        f = snapshot.facility
        lines.append(
            "- Facility: "
            f"{f.name or 'unknown'}; phone {f.phone or 'not listed'}; "
            f"emergency phone {f.emergency_phone or 'not listed'}; "
            f"hours {f.operating_hours or 'not listed'}"
        )
    if snapshot.active_package_name:
        lines.append(f"- Active package: {snapshot.active_package_name}")

    lines.append("")
    lines.append("## App permissions (as last reported by the app)")
    if "permissions" in errs:
        lines.append(f"- {SNAPSHOT_UNAVAILABLE}")
    elif snapshot.permissions is None:
        lines.append("- The app has never reported permission state for this patient.")
    else:
        p = snapshot.permissions

        def _flag(v: bool | None) -> str:
            return "unknown" if v is None else ("ON" if v else "OFF")

        lines.append(
            f"- Notifications {_flag(p.notifications)}, Health {_flag(p.health)}, "
            f"Camera {_flag(p.camera)}, Gallery {_flag(p.gallery)}, "
            f"Storage {_flag(p.storage)} (reported {_fmt_dt(p.synced_at)})"
        )

    lines.append("")
    lines.append("## Glucose sources")
    if "glucose_sources" in errs:
        lines.append(f"- {SNAPSHOT_UNAVAILABLE}")
    elif not snapshot.glucose_sources:
        lines.append("- No CGM source connected (no LibreView ID or Sinocare on file).")
    else:
        for src in snapshot.glucose_sources:
            live = ""
            if src.live_polling_enabled is not None:
                live = (
                    f"; live polling {'on' if src.live_polling_enabled else 'off'}"
                    f" (last {_fmt_dt(src.live_last_sync_at)})"
                )
            lines.append(
                f"- {src.provider}: sync status {src.sync_status or 'unknown'}; "
                f"last sync {_fmt_dt(src.last_sync_at)}; "
                f"last reading {_fmt_dt(src.last_reading_at)}{live}"
            )

    lines.append("")
    lines.append("## Meals")
    if "meals" in errs:
        lines.append(f"- {SNAPSHOT_UNAVAILABLE}")
    else:
        lines.append(
            f"- Last saved meal: {snapshot.last_meal_date or 'none on record'}; "
            f"meals saved in the last 7 days: "
            f"{snapshot.meals_last_7_days if snapshot.meals_last_7_days is not None else 'unknown'}"
        )

    lines.append("")
    lines.append("## Recent documents that reached the server")
    if "documents" in errs:
        lines.append(f"- {SNAPSHOT_UNAVAILABLE}")
    elif not snapshot.recent_documents:
        lines.append("- None on record.")
    else:
        for d in snapshot.recent_documents:
            lines.append(
                f"- {d.file_name or 'unnamed'} ({d.category or 'document'}), "
                f"uploaded {_fmt_dt(d.uploaded_at)}"
            )

    lines.append("")
    lines.append("## Phone and app")
    if "device" in errs:
        lines.append(f"- {SNAPSHOT_UNAVAILABLE}")
    elif snapshot.device is None:
        lines.append("- No device registered.")
    else:
        d = snapshot.device
        lines.append(
            f"- {d.platform or 'unknown platform'} {d.os_version or ''}".rstrip()
            + f", {d.model or 'unknown model'}, app version {d.app_version or 'unknown'}, "
            f"last active {_fmt_dt(d.last_active_at)}"
        )
    return "\n".join(lines)


class SupportAssistantAgent(BaseAgent):
    """Triage + reply for one patient message in a support ticket."""

    agent_id = "support_assistant"

    def __init__(
        self, *, gateway, memory=None, prompts=None, event_bus=None, translator=None
    ) -> None:
        super().__init__(gateway=gateway, memory=memory, prompts=prompts, event_bus=event_bus)
        self.translator = translator
        # Loaded once at startup; edit the files + restart to change content.
        self._system_message = _load_brain()

    # -- Public API -----------------------------------------------------------

    async def run(self, input: AgentInput) -> AgentOutput:
        start = time.perf_counter()
        trace_id = input.context.trace_id or f"trc_{uuid4().hex[:16]}"
        self.gateway.set_langfuse_context(
            session_id=input.context.thread_id, user_id=input.context.user_id
        )
        self.gateway.langfuse_trace_input(
            trace_id=trace_id, name=self.agent_id, input_text=input.message
        )

        snapshot = self._coerce_snapshot(input.metadata.get("snapshot"))
        language = self._effective_language(input, snapshot)
        history = self._coerce_history(input.metadata.get("history"))
        messages = self._build_messages(input.message, history, snapshot, language)

        try:
            triage, meta = await self.gateway.extract(
                messages=messages,
                response_model=SupportTriage,
                task=ModelTask.SUPPORT_ASSISTANT,
                temperature=settings.SUPPORT_ASSISTANT_TEMPERATURE,
                timeout=settings.SUPPORT_ASSISTANT_TIMEOUT_SECONDS,
                trace_id=trace_id,
            )
        except Exception as exc:
            logger.exception("SupportAssistant triage failed: %s", exc)
            return await self._failure_output(language, trace_id, start)

        mode = self._decide_mode(triage)
        message = await self._compose(triage, mode, snapshot, language, trace_id)

        latency_ms = int((time.perf_counter() - start) * 1000)
        self.gateway.langfuse_trace_output(trace_id=trace_id, output_text=message)
        cost = getattr(meta, "cost", None)
        return AgentOutput(
            message=message,
            trace_id=trace_id,
            cost_usd=cost.total_cost if cost else None,
            latency_ms=latency_ms,
            model_id=getattr(meta, "model_id", None),
            data={
                "category": triage.category.value,
                "urgency": triage.urgency.value,
                "needs_human": triage.needs_human or mode != HandlingMode.ANSWERED,
                "summary": triage.summary,
                "handling_mode": mode.value,
                "language": language,
            },
        )

    # -- Policy ---------------------------------------------------------------

    @staticmethod
    def _decide_mode(triage: SupportTriage) -> HandlingMode:
        """Policy is code, not prompt: the category decides the mode even if
        the model's ``needs_human`` flag disagrees."""
        if triage.category == SupportCategory.EMERGENCY:
            return HandlingMode.EMERGENCY
        if triage.category == SupportCategory.MEDICAL_QUESTION:
            return HandlingMode.REDIRECTED_MEDICAL
        if triage.category not in SELF_SERVE_CATEGORIES or triage.needs_human:
            return HandlingMode.HELD_FOR_HUMAN
        if not triage.reply.strip():
            return HandlingMode.HELD_FOR_HUMAN
        return HandlingMode.ANSWERED

    async def _compose(
        self,
        triage: SupportTriage,
        mode: HandlingMode,
        snapshot: SupportSnapshot,
        language: str,
        trace_id: str,
    ) -> str:
        reply = triage.reply.strip()

        if mode == HandlingMode.ANSWERED:
            return reply

        if mode == HandlingMode.HELD_FOR_HUMAN:
            hold = await self._t(HOLD_MESSAGE, language, trace_id)
            return f"{reply}\n\n{hold}" if reply else hold

        if mode == HandlingMode.REDIRECTED_MEDICAL:
            contacts = [c for c in snapshot.care_team if c.is_active] or snapshot.care_team
            # The model is told not to list contacts, but if it did anyway,
            # appending the same numbers again reads as a glitch. Any care-team
            # phone/email already in the reply means the redirect is done.
            already_listed = any(
                (c.phone and c.phone in reply) or (c.email and c.email in reply)
                for c in contacts
            )
            if already_listed:
                return reply
            if contacts:
                lead = await self._t(MEDICAL_REDIRECT_WITH_CONTACT, language, trace_id)
                block = "\n".join(f"- {_contact_line(c)}" for c in contacts)
                redirect = f"{lead}\n{block}"
            else:
                redirect = await self._t(MEDICAL_REDIRECT_NO_CONTACT, language, trace_id)
            return f"{reply}\n\n{redirect}" if reply else redirect

        # EMERGENCY: the model's reply is discarded on purpose.
        parts = [await self._t(EMERGENCY_MESSAGE, language, trace_id)]
        if snapshot.facility and snapshot.facility.emergency_phone:
            lead = await self._t(EMERGENCY_FACILITY_LINE, language, trace_id)
            parts.append(f"{lead} {snapshot.facility.emergency_phone}")
        contacts = [c for c in snapshot.care_team if c.phone]
        if contacts:
            lead = await self._t(EMERGENCY_CARE_TEAM_LINE, language, trace_id)
            parts.append(lead + "\n" + "\n".join(f"- {_contact_line(c)}" for c in contacts))
        parts.append(await self._t(EMERGENCY_FLAGGED, language, trace_id))
        return "\n\n".join(parts)

    async def _failure_output(self, language: str, trace_id: str, start: float) -> AgentOutput:
        """LLM unavailable: still leave the patient with an honest hold
        message and mark the ticket for a human. Never silent."""
        message = await self._t(HOLD_MESSAGE_AFTER_FAILURE, language, trace_id)
        return AgentOutput(
            message=message,
            is_ready=False,
            trace_id=trace_id,
            latency_ms=int((time.perf_counter() - start) * 1000),
            data={
                "category": SupportCategory.UNKNOWN.value,
                "urgency": SupportUrgency.NORMAL.value,
                "needs_human": True,
                "summary": "Assistant could not process this message (LLM error); needs a person.",
                "handling_mode": HandlingMode.HELD_FOR_HUMAN.value,
                "language": language,
                "error": True,
            },
        )

    # -- Prompt assembly ------------------------------------------------------

    def _build_messages(
        self,
        user_message: str,
        history: list[dict[str, str]],
        snapshot: SupportSnapshot,
        language: str,
    ) -> list[dict[str, str]]:
        language_instruction = (
            f"Write the `reply` in {ai_language_name(language)} "
            f"(language code: {language}). Keep app screen and button names in English. "
            "The `summary` is always in English."
        )
        return [
            {"role": "system", "content": self._system_message},
            {"role": "system", "content": render_snapshot(snapshot)},
            {"role": "system", "content": language_instruction},
            *history,
            {"role": "user", "content": user_message},
        ]

    @staticmethod
    def _effective_language(input: AgentInput, snapshot: SupportSnapshot) -> str:
        explicit = input.context.metadata.get("language") or input.metadata.get("language")
        return str(explicit or snapshot.language or DEFAULT_AI_LANGUAGE)

    @staticmethod
    def _coerce_snapshot(raw: Any) -> SupportSnapshot:
        if isinstance(raw, SupportSnapshot):
            return raw
        if isinstance(raw, dict):
            try:
                return SupportSnapshot.model_validate(raw)
            except Exception as exc:  # malformed snapshot must not block a reply
                logger.warning("SupportAssistant: ignoring malformed snapshot: %s", exc)
        return SupportSnapshot(lookup_errors=[
            "care_team", "permissions", "glucose_sources", "meals", "documents", "device",
        ])

    @staticmethod
    def _coerce_history(raw: Any) -> list[dict[str, str]]:
        """Accept [{role, content}, ...] oldest first; keep recent clean turns."""
        if not isinstance(raw, list):
            return []
        clean: list[dict[str, str]] = []
        for turn in raw[-settings.SUPPORT_ASSISTANT_HISTORY_MESSAGES:]:
            if (
                isinstance(turn, dict)
                and turn.get("role") in {"user", "assistant"}
                and turn.get("content")
            ):
                clean.append({"role": turn["role"], "content": str(turn["content"])})
        return clean

    async def _t(self, text: str, language: str, trace_id: str) -> str:
        """Translate a fixed canonical string; English or no translator → as is."""
        if language == DEFAULT_AI_LANGUAGE or self.translator is None:
            return text
        try:
            return await self.translator.translate_cached(text, language, trace_id=trace_id)
        except Exception as exc:
            logger.warning("SupportAssistant translation failed (%s): %s", language, exc)
            return text
