"""Unified Profile Agent service.

Replaces `ProfileUpdateAgentService` and `PatientOnboardingAgentService`.
Schema-driven field discovery, mode-aware conversation, single Postgres
transaction apply.

Key design points:
  * LLM used only for intent extraction.
  * Deterministic reducer + FSM consume the LLM output; all mutation is
    in our control.
  * Gap detection and mode selection run every turn from the current
    ORM state merged with the in-progress draft.
  * `profile_completion` JSONB is RECOMPUTED from source (not just flagged).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorCollection
from openai import AsyncOpenAI
from pymongo.errors import DuplicateKeyError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.schemas.patient import CorePatientProfile
from lib.schemas.profile_agent import (
    DraftState,
    GapReport,
    LLMAction,
    ProfileAgentChatResponse,
    SessionSummaryResponse,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.services.profile_agent.applier import apply_coerced_changes
from lib.services.profile_agent.completion import recompute_profile_completion
from lib.services.profile_agent.config import FIELD_TO_CONFIG
from lib.services.profile_agent.fsm import (
    SIG_CANCEL,
    SIG_CONTINUE,
    SIG_REVIEW,
    reduce_draft,
)
from lib.services.profile_agent.gap_detector import compute_gap_report, next_missing_field
from lib.services.profile_agent.gate_inference import infer_gate_fields
from lib.services.profile_agent.llm import extract_intent
from lib.services.profile_agent.validators import validate_draft
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)

# Deterministic confirmation phrases — inject confirm_all when the LLM
# missed it but the user clearly said yes.
_CONFIRM_PHRASES = {
    "confirm", "confirm all", "yes", "yes confirm", "yes, confirm",
    "go ahead", "looks good", "do it", "yes please", "yes, please",
    "confirm changes", "confirm these changes", "save", "save changes",
    "apply", "apply changes", "lgtm",
}


class ProfileAgentService:
    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_profile_service: PatientProfileService,
        conversation_collection: AsyncIOMotorCollection,
    ) -> None:
        self.postgres_store = postgres_store
        self.patient_profile_service = patient_profile_service
        self.conversation_collection = conversation_collection
        self.openai_client = AsyncOpenAI()

    async def ensure_indexes(self) -> None:
        await self.conversation_collection.create_index(
            [("patient_id", 1)],
            unique=True,
            partialFilterExpression={"status": "active"},
            name="unique_active_profile_agent_draft_per_patient",
        )

    # ── Public API ─────────────────────────────────────────────────────

    async def start(self, patient_id: str, restart: bool = False) -> ProfileAgentChatResponse:
        """Begin or resume a session. Returns the first proactive prompt."""
        if restart:
            await self.conversation_collection.update_many(
                {"patient_id": patient_id, "status": "active"},
                {"$set": {"status": "cancelled"}},
            )

        draft = await self._get_or_create_draft(patient_id)
        patient = await self._fetch_patient(patient_id)
        report = compute_gap_report(patient, draft.get("draft_changes", {}))
        nxt = next_missing_field(report)

        reply = self._opening_reply(report.mode, nxt)
        draft["messages"].append({"role": "assistant", "content": reply})
        await self._save_draft(draft)

        return ProfileAgentChatResponse(
            reply=reply,
            state=draft["state"],
            mode=report.mode,
            draft_changes=draft.get("draft_changes") or None,
            next_field=nxt.field if nxt else None,
        )

    async def chat(self, patient_id: str, message: str) -> ProfileAgentChatResponse:
        draft = await self._get_or_create_draft(patient_id)

        # Fresh-start on new message after a terminal state.
        if draft.get("state") in (DraftState.COMPLETED.value, DraftState.CANCELLED.value):
            draft["state"] = DraftState.COLLECTING.value
            draft["draft_changes"] = {}

        # Drop stale keys from draft (config may have changed since last turn).
        draft["draft_changes"] = {
            k: v for k, v in draft.get("draft_changes", {}).items()
            if k in FIELD_TO_CONFIG
        }

        draft["messages"].append({"role": "user", "content": message})

        patient = await self._fetch_patient(patient_id)
        report = compute_gap_report(patient, draft["draft_changes"])
        nxt = next_missing_field(report)
        profile_ctx = self._profile_context_json(patient)

        parsed = await extract_intent(
            self.openai_client,
            draft["messages"],
            mode=report.mode,
            profile_context_json=profile_ctx,
            next_field=nxt,
            pending_draft=draft["draft_changes"],
        )

        # Deterministic confirm-phrase fallback.
        has_confirm_cancel = any(
            a.action in ("confirm_all", "cancel_all") for a in parsed.actions
        )
        if (
            not has_confirm_cancel
            and draft["draft_changes"]
            and message.strip().lower().rstrip(".!") in _CONFIRM_PHRASES
        ):
            parsed.actions.append(LLMAction(action="confirm_all"))

        # User-provided-value hallucination guard needs user-messages history.
        user_text = " ".join(
            m["content"] for m in draft["messages"] if m["role"] == "user"
        )

        response = await self._advance(
            draft=draft,
            patient_id=patient_id,
            actions=parsed.actions,
            llm_reply=parsed.reply,
            user_messages_text=user_text,
            report=report,
            next_field_key=nxt.field if nxt else None,
        )

        # Auto-infer gate fields: if the LLM set a gated field but forgot
        # the gate (e.g. "I smoke 10/day" → cigarettes_per_day=10 without
        # smoke_status=true), fill the gate so data stays consistent.
        if draft.get("draft_changes"):
            infer_gate_fields(patient, draft["draft_changes"])

        # Recompute next_field against the updated draft so clients see
        # the truly-next field to collect (not the one that was next
        # before this turn).
        post_report = compute_gap_report(patient, draft.get("draft_changes", {}))
        post_nxt = next_missing_field(post_report)
        if response.state == DraftState.COLLECTING.value:
            response.next_field = post_nxt.field if post_nxt else None
            response.mode = post_report.mode

        draft["messages"].append({"role": "assistant", "content": response.reply})
        await self._save_draft(draft)
        return response

    async def get_active_session(self, patient_id: str) -> Optional[SessionSummaryResponse]:
        doc = await self.conversation_collection.find_one(
            {"patient_id": patient_id, "status": "active"}
        )
        if not doc:
            return None
        # Compute mode fresh for accuracy.
        patient = await self._fetch_patient(patient_id)
        report = compute_gap_report(patient, doc.get("draft_changes", {}))
        return SessionSummaryResponse(
            state=doc.get("state", DraftState.COLLECTING.value),
            mode=report.mode,
            draft_changes=doc.get("draft_changes", {}),
            message_count=len(doc.get("messages", [])),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )

    async def get_gaps(self, patient_id: str) -> GapReport:
        patient = await self._fetch_patient(patient_id)
        # Include the active draft so gaps reflect in-flight answers.
        doc = await self.conversation_collection.find_one(
            {"patient_id": patient_id, "status": "active"}
        )
        draft_changes = (doc or {}).get("draft_changes", {})
        return compute_gap_report(patient, draft_changes)

    # ── Internal ───────────────────────────────────────────────────────

    async def _advance(
        self,
        *,
        draft: Dict[str, Any],
        patient_id: str,
        actions: List[LLMAction],
        llm_reply: str,
        user_messages_text: str,
        report: GapReport,
        next_field_key: Optional[str],
    ) -> ProfileAgentChatResponse:
        state = DraftState(draft.get("state", DraftState.COLLECTING.value))
        draft_changes: Dict[str, Any] = draft.get("draft_changes", {})

        if state == DraftState.COLLECTING:
            draft_changes, signal, dropped = reduce_draft(
                draft_changes, actions, user_messages_text
            )
            draft["draft_changes"] = draft_changes

            if signal == SIG_CANCEL:
                draft["state"] = DraftState.CANCELLED.value
                draft["status"] = "cancelled"
                return ProfileAgentChatResponse(
                    reply=llm_reply or "All changes cancelled. Start again whenever you're ready.",
                    state=DraftState.CANCELLED.value,
                    mode=report.mode,
                )

            if signal == SIG_REVIEW:
                if not draft_changes:
                    return ProfileAgentChatResponse(
                        reply="There's nothing to confirm yet. Tell me what you'd like to update.",
                        state=DraftState.COLLECTING.value,
                        mode=report.mode,
                        next_field=next_field_key,
                    )
                draft["state"] = DraftState.REVIEWING.value
                return ProfileAgentChatResponse(
                    reply=self._build_review_summary(draft_changes),
                    state=DraftState.REVIEWING.value,
                    mode=report.mode,
                    draft_changes=draft_changes,
                )

            if dropped:
                labels = ", ".join(
                    FIELD_TO_CONFIG[f]["label"].lower() for f in dropped if f in FIELD_TO_CONFIG
                )
                reply = f"What would you like to change your {labels} to?"
            else:
                reply = llm_reply or "What would you like to update?"

            return ProfileAgentChatResponse(
                reply=reply,
                state=DraftState.COLLECTING.value,
                mode=report.mode,
                draft_changes=draft_changes or None,
                next_field=next_field_key,
            )

        if state == DraftState.REVIEWING:
            draft_changes, signal, _ = reduce_draft(draft_changes, actions, user_messages_text)
            draft["draft_changes"] = draft_changes

            if signal == SIG_CANCEL:
                draft["state"] = DraftState.CANCELLED.value
                draft["status"] = "cancelled"
                return ProfileAgentChatResponse(
                    reply=llm_reply or "All changes cancelled.",
                    state=DraftState.CANCELLED.value,
                    mode=report.mode,
                )

            if signal == SIG_REVIEW:
                if not draft_changes:
                    draft["state"] = DraftState.COLLECTING.value
                    return ProfileAgentChatResponse(
                        reply="The draft is empty — nothing to confirm.",
                        state=DraftState.COLLECTING.value,
                        mode=report.mode,
                    )

                coerced, errors = validate_draft(draft_changes)
                if errors:
                    draft["state"] = DraftState.COLLECTING.value
                    msg = "Some values need fixing:\n" + "\n".join(f"• {e}" for e in errors)
                    return ProfileAgentChatResponse(
                        reply=msg,
                        state=DraftState.COLLECTING.value,
                        mode=report.mode,
                        draft_changes=draft_changes,
                    )

                try:
                    await self._apply_batch(patient_id, coerced)
                except Exception:
                    logger.exception("apply failed for patient %s", patient_id)
                    return ProfileAgentChatResponse(
                        reply="Something went wrong saving your changes. Please try again.",
                        state=DraftState.REVIEWING.value,
                        mode=report.mode,
                        draft_changes=draft_changes,
                    )

                # Re-read the patient so we can prompt the next gap in the
                # same turn instead of stranding the user after "Done!".
                updated_patient = await self._fetch_patient(patient_id)
                post_report = compute_gap_report(updated_patient, {})
                next_missing = next_missing_field(post_report)

                # Reset the draft so follow-up answers start a fresh batch
                # in COLLECTING state on the next user message.
                draft["state"] = DraftState.COLLECTING.value
                draft["status"] = "collecting"
                draft["draft_changes"] = {}
                applied = {k: _stringify(v) for k, v in coerced.items()}
                labels = ", ".join(
                    FIELD_TO_CONFIG[f]["label"] for f in applied if f in FIELD_TO_CONFIG
                )
                reply = f"Done! Updated: {labels}."
                if next_missing:
                    reply += f" Next — what's your {next_missing.label.lower()}?"
                else:
                    reply += " Your profile is all set."
                return ProfileAgentChatResponse(
                    reply=reply,
                    state=DraftState.COLLECTING.value,
                    mode=post_report.mode,
                    applied_changes=applied,
                    next_field=next_missing.field if next_missing else None,
                )

            # User made further edits while reviewing — bounce to COLLECTING.
            draft["state"] = DraftState.COLLECTING.value
            return ProfileAgentChatResponse(
                reply=llm_reply or "Draft updated. Let me know when to confirm.",
                state=DraftState.COLLECTING.value,
                mode=report.mode,
                draft_changes=draft_changes or None,
                next_field=next_field_key,
            )

        # Defensive fallback.
        return ProfileAgentChatResponse(
            reply="Something went wrong. Please start over.",
            state=DraftState.COLLECTING.value,
            mode=report.mode,
        )

    # ── Apply path ─────────────────────────────────────────────────────

    @with_postgres_session
    async def _apply_batch(
        self,
        patient_id: str,
        coerced: Dict[str, Any],
        *,
        postgres_session: AsyncSession,
    ) -> None:
        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id, detailed=True, postgres_session=postgres_session
        )
        apply_coerced_changes(patient, coerced)
        recompute_profile_completion(patient)

        postgres_session.add(patient)
        await postgres_session.commit()
        logger.info(
            "profile-agent applied fields for %s: %s",
            patient_id, ", ".join(coerced.keys()),
        )

        # Post-commit side effects — best-effort.
        try:
            await self.patient_profile_service.chat_notification_service.notify_participants(
                message_key="chat_list_updated", user_id=patient_id,
            )
        except Exception:
            logger.warning("chat notify failed for %s", patient_id, exc_info=True)

        try:
            from lib.workers.tasks.profile.enqueue import enqueue_generate_profile_vector_sync

            await postgres_session.refresh(patient)
            detailed = await self.patient_profile_service.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )
            profile_data = CorePatientProfile.from_orm(detailed).model_dump(mode="json")
            enqueue_generate_profile_vector_sync(patient_id, profile_data)
        except Exception:
            logger.warning("vector enqueue failed for %s", patient_id, exc_info=True)

    # ── Helpers ────────────────────────────────────────────────────────

    @with_postgres_session
    async def _fetch_patient(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ):
        return await self.patient_profile_service.fetch_patient_profile(
            patient_id, detailed=True, postgres_session=postgres_session
        )

    def _profile_context_json(self, patient) -> Optional[str]:
        try:
            data = CorePatientProfile.from_orm(patient).model_dump(mode="json")
            # Trim obvious irrelevants so the prompt stays small.
            for k in (
                "permissions", "connected_apps", "care_providers",
                "package_assignments", "current_package", "smbgs",
                "weight_loss_enrollment", "diet_plans", "fitness_plans",
            ):
                data.pop(k, None)
            return json.dumps(data, indent=2, default=str)
        except Exception:
            logger.warning("profile context serialisation failed", exc_info=True)
            return None

    def _opening_reply(self, mode: str, nxt) -> str:
        if mode == "onboarding_fresh":
            if nxt:
                return f"Welcome! Let's set up your profile. What's your {nxt.label.lower()}?"
            return "Welcome! Your profile is ready — anything you'd like to update?"
        if mode == "onboarding_resuming":
            if nxt:
                return f"Welcome back. Let's continue — what's your {nxt.label.lower()}?"
            return "Welcome back! Your profile is complete."
        if mode == "hybrid":
            if nxt:
                return f"A few things still to fill in. What's your {nxt.label.lower()}?"
            return "Your profile looks good. Anything to update?"
        return "Your profile is all set. What would you like to change?"

    def _build_review_summary(self, draft_changes: Dict[str, Any]) -> str:
        lines = [
            f"• {FIELD_TO_CONFIG[k]['label']} → {_stringify(v)}"
            for k, v in draft_changes.items()
            if k in FIELD_TO_CONFIG
        ]
        return "Here's what I'll update:\n" + "\n".join(lines) + "\n\nShall I confirm these changes?"

    # ── Mongo ──────────────────────────────────────────────────────────

    async def _get_or_create_draft(self, patient_id: str) -> Dict[str, Any]:
        doc = await self.conversation_collection.find_one(
            {"patient_id": patient_id, "status": "active"}
        )
        if doc:
            return doc

        now = datetime.now(timezone.utc).isoformat()
        new_doc: Dict[str, Any] = {
            "patient_id": patient_id,
            "status": "active",
            "state": DraftState.COLLECTING.value,
            "draft_changes": {},
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        try:
            await self.conversation_collection.insert_one(new_doc)
        except DuplicateKeyError:
            existing = await self.conversation_collection.find_one(
                {"patient_id": patient_id, "status": "active"}
            )
            if existing:
                return existing
        return new_doc

    async def _save_draft(self, draft: Dict[str, Any]) -> None:
        draft["updated_at"] = datetime.now(timezone.utc).isoformat()
        # Filter by _id when possible so status transitions (active →
        # cancelled/completed) update the same doc. Fallback to
        # (patient_id, status="active") for newly-created drafts that
        # haven't been persisted yet.
        if "_id" in draft:
            await self.conversation_collection.replace_one(
                {"_id": draft["_id"]}, draft, upsert=False,
            )
        else:
            await self.conversation_collection.replace_one(
                {"patient_id": draft["patient_id"], "status": "active"},
                draft,
                upsert=True,
            )


def _stringify(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(x) for x in value)
    return str(value)
