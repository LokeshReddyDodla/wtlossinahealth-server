"""Profile Update micro-agent service — draft-change-set workflow.

Manages a multi-turn conversation where the patient can propose, modify, and
remove profile changes.  Changes accumulate in an in-memory Mongo-backed
*draft*.  **No database write happens until the user gives final
confirmation** for the entire draft.

Architecture
~~~~~~~~~~~~
* **Prompting / parsing** — ``_extract_intent`` calls the LLM and returns a
  structured ``LLMResponse`` (list of actions + reply text).
* **Draft reducer** — ``_reduce_draft`` is a pure function that applies
  parsed actions to the in-memory draft dict.  It is the *single source of
  truth* for how draft changes are added, replaced, and removed.
* **Validation / coercion** — ``_coerce_value`` and ``_validate_draft``
  convert raw string values to typed Python objects and reject bad input.
* **Persistence** — ``_apply_draft_batch`` writes all approved changes to
  Postgres in **one transaction** (all-or-nothing).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date as _date
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorCollection
from openai import AsyncOpenAI
from pymongo.errors import DuplicateKeyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient as PatientModel
from lib.models.patient_alcohol_consumption import (
    PatientAlcoholConsumption as PatientAlcoholConsumptionModel,
)
from lib.models.patient_daily_activity import (
    PatientDailyActivity as PatientDailyActivityModel,
)
from lib.models.patient_diabetic_history import (
    PatientDiabeticHistory as PatientDiabeticHistoryModel,
)
from lib.models.patient_drug_allergy import (
    PatientDrugAllergy as PatientDrugAllergyModel,
)
from lib.models.patient_eating_habit import (
    PatientEatingHabit as PatientEatingHabitModel,
)
from lib.models.patient_food_allergy import (
    PatientFoodAllergy as PatientFoodAllergyModel,
)
from lib.models.patient_medical_history import (
    PatientMedicalHistory as PatientMedicalHistoryModel,
)
from lib.models.patient_sleep_habit import (
    PatientSleepHabit as PatientSleepHabitModel,
)
from lib.models.patient_smoking_habit import (
    PatientSmokingHabit as PatientSmokingHabitModel,
)
from lib.schemas.profile_update_agent import (
    BASIC_FIELDS,
    FIELD_TO_SECTION,
    LIFESTYLE_FIELDS,
    MEDICAL_HISTORY_FIELDS,
    DraftState,
    DraftSummaryResponse,
    LLMAction,
    LLMResponse,
    ProfileUpdateChatResponse,
    UpdatableField,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.services.profile_update_agent.prompts import SYSTEM_PROMPT
from lib.utils.postgres_session_decorator import with_postgres_session

logger = logging.getLogger(__name__)

# OpenAI model to use — centralised so it's easy to change later.
_LLM_MODEL = "gpt-4o-mini"

# ── Validation constants ────────────────────────────────────────────────────
_VALID_GENDERS = {"male", "female", "other"}
_VALID_ACTIVITY_LEVELS = {"sedentary", "light", "moderate", "active", "very_active"}
_VALID_SLEEP_QUALITIES = {"good", "average", "poor"}
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_BOOL_TRUE = {"yes", "true", "1", "y"}
_BOOL_FALSE = {"no", "false", "0", "n"}

# Deterministic confirmation phrases — if the user's message (lowered &
# stripped) matches one of these AND the LLM didn't already emit a
# confirm_all/cancel_all, we inject confirm_all ourselves.  This guards
# against LLM flakiness on short affirmative replies.
_CONFIRM_PHRASES = {
    "confirm",
    "confirm all",
    "yes",
    "yes confirm",
    "yes, confirm",
    "go ahead",
    "looks good",
    "do it",
    "yes please",
    "yes, please",
    "confirm changes",
    "confirm these changes",
    "yes, confirm these changes",
    "yes confirm all",
    "yes, confirm all",
    "lgtm",
    "save",
    "save changes",
    "apply",
    "apply changes",
}

# Canonical field names — used for quick membership tests.
_VALID_FIELDS = {f.value for f in UpdatableField}

# Fields where the exact value MUST appear in a user message.  The LLM is
# prone to hallucinating common names (e.g. "Smith") when the user hasn't
# actually provided a value.  For these fields we enforce that the value the
# LLM emitted can be found verbatim in the user's conversation history.
_USER_PROVIDED_VALUE_FIELDS = {"first_name", "last_name"}

# Reducer signals returned alongside the mutated draft.
_SIG_CONTINUE = "continue"
_SIG_REVIEW = "review"
_SIG_CANCEL = "cancel"


class ProfileUpdateAgentService:
    """Draft-change-set conversational agent for profile updates.

    Design decisions
    ~~~~~~~~~~~~~~~~
    * One *active* Mongo document per patient (``status == "active"``).
    * The LLM is only used for *intent extraction* — all mutation logic is
      deterministic so it can be tested / audited without an LLM.
    * No DB write happens until the patient gives final confirmation.
    * The batch-apply path runs in a single Postgres transaction.
    """

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

    # ── One-time index setup ────────────────────────────────────────────────
    async def ensure_indexes(self) -> None:
        """Create a unique partial index so only one active draft per patient
        can exist.  Safe to call on every boot — Mongo ignores duplicates."""
        await self.conversation_collection.create_index(
            [("patient_id", 1)],
            unique=True,
            partialFilterExpression={"status": "active"},
            name="unique_active_draft_per_patient",
        )

    # ═══════════════════════════════════════════════════════════════════════
    #  Public API
    # ═══════════════════════════════════════════════════════════════════════

    async def chat(
        self,
        patient_id: str,
        message: str,
    ) -> ProfileUpdateChatResponse:
        """Process a single user turn and return the agent's reply."""

        # 1. Load or create the active draft for this patient.
        draft = await self._get_or_create_draft(patient_id)

        # 2. Append user message to history.
        draft["messages"].append({"role": "user", "content": message})

        # 2b. Fetch current profile for LLM context.
        profile_context = await self._fetch_profile_context(patient_id)

        # 3. Ask the LLM to extract intent.
        parsed = await self._extract_intent(
            draft["messages"], profile_context=profile_context
        )

        # 3b. Guard against hallucinated values: for name fields, verify the
        #     value actually appears in the user's messages.  If not, the LLM
        #     invented it — drop the action and ask the user for the real value.
        user_texts = " ".join(
            m["content"] for m in draft["messages"] if m["role"] == "user"
        ).lower()
        filtered_actions: list[LLMAction] = []
        hallucinated_fields: list[str] = []
        for act in parsed.actions:
            if (
                act.action == "set"
                and act.field in _USER_PROVIDED_VALUE_FIELDS
                and act.value
                and act.value.lower() not in user_texts
            ):
                hallucinated_fields.append(act.field)
                logger.warning(
                    "Blocked hallucinated value for %s: '%s' (not in user messages)",
                    act.field, act.value,
                )
                continue
            filtered_actions.append(act)
        if hallucinated_fields:
            labels = UpdatableField.human_labels()
            field_names = " and ".join(
                labels.get(f, f).lower() for f in hallucinated_fields
            )
            parsed.actions = filtered_actions
            parsed.reply = f"What would you like to change your {field_names} to?"

        # 3c. Deterministic fallback: if the user clearly wants to confirm
        #     but the LLM didn't emit confirm_all (or cancel_all), inject it.
        has_confirm_or_cancel = any(
            a.action in ("confirm_all", "cancel_all") for a in parsed.actions
        )
        if (
            not has_confirm_or_cancel
            and draft.get("draft_changes")
            and message.strip().lower().rstrip(".!") in _CONFIRM_PHRASES
        ):
            parsed.actions.append(LLMAction(action="confirm_all"))

        # 4. Advance FSM — may modify draft and/or write to Postgres.
        response = await self._advance_state(draft, parsed, patient_id)

        # 5. Append assistant reply and persist draft.
        draft["messages"].append({"role": "assistant", "content": response.reply})
        await self._save_draft(draft)

        return response

    async def get_active_draft(
        self,
        patient_id: str,
    ) -> Optional[DraftSummaryResponse]:
        """Return the current active draft summary, or *None*."""
        doc = await self.conversation_collection.find_one(
            {"patient_id": patient_id, "status": "active"}
        )
        if not doc:
            return None
        return DraftSummaryResponse(
            state=doc.get("state", DraftState.COLLECTING.value),
            draft_changes=doc.get("draft_changes", {}),
            message_count=len(doc.get("messages", [])),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )

    # ═══════════════════════════════════════════════════════════════════════
    #  FSM logic
    # ═══════════════════════════════════════════════════════════════════════

    async def _advance_state(
        self,
        draft: Dict[str, Any],
        parsed: LLMResponse,
        patient_id: str,
    ) -> ProfileUpdateChatResponse:
        """Deterministic state-machine that decides what to do next."""

        state = DraftState(draft.get("state", DraftState.COLLECTING.value))
        draft_changes: Dict[str, str] = draft.get("draft_changes", {})
        llm_reply: str = parsed.reply
        actions = parsed.actions

        # If the draft was completed/cancelled and the user sends a new
        # message, start a fresh collecting session.
        if state in (DraftState.COMPLETED, DraftState.CANCELLED):
            draft["state"] = DraftState.COLLECTING.value
            draft["draft_changes"] = {}
            draft_changes = draft["draft_changes"]
            state = DraftState.COLLECTING

        # ── COLLECTING ──────────────────────────────────────────────────────
        if state == DraftState.COLLECTING:
            draft_changes, signal = self._reduce_draft(draft_changes, actions)
            draft["draft_changes"] = draft_changes

            if signal == _SIG_CANCEL:
                draft["state"] = DraftState.CANCELLED.value
                draft["status"] = "cancelled"
                return ProfileUpdateChatResponse(
                    reply=llm_reply or "All changes cancelled. Start a new request whenever you're ready.",
                    state=DraftState.CANCELLED.value,
                    draft_changes=None,
                )

            if signal == _SIG_REVIEW:
                if not draft_changes:
                    # Nothing to confirm.
                    return ProfileUpdateChatResponse(
                        reply="There are no pending changes to confirm. Tell me what you'd like to update.",
                        state=DraftState.COLLECTING.value,
                        draft_changes=draft_changes,
                    )
                # Transition to REVIEWING.
                draft["state"] = DraftState.REVIEWING.value
                summary = self._build_review_summary(draft_changes)
                return ProfileUpdateChatResponse(
                    reply=summary,
                    state=DraftState.REVIEWING.value,
                    draft_changes=draft_changes,
                )

            # signal == _SIG_CONTINUE — stay collecting.
            reply = llm_reply or "What would you like to update?"
            return ProfileUpdateChatResponse(
                reply=reply,
                state=DraftState.COLLECTING.value,
                draft_changes=draft_changes if draft_changes else None,
            )

        # ── REVIEWING ───────────────────────────────────────────────────────
        if state == DraftState.REVIEWING:
            # The user may confirm, cancel, or make further edits.
            draft_changes, signal = self._reduce_draft(draft_changes, actions)
            draft["draft_changes"] = draft_changes

            if signal == _SIG_CANCEL:
                draft["state"] = DraftState.CANCELLED.value
                draft["status"] = "cancelled"
                return ProfileUpdateChatResponse(
                    reply=llm_reply or "All changes cancelled.",
                    state=DraftState.CANCELLED.value,
                    draft_changes=None,
                )

            if signal == _SIG_REVIEW:
                # User confirmed — validate & apply.
                if not draft_changes:
                    draft["state"] = DraftState.COLLECTING.value
                    return ProfileUpdateChatResponse(
                        reply="The draft is now empty — nothing to confirm. Tell me what you'd like to change.",
                        state=DraftState.COLLECTING.value,
                        draft_changes=None,
                    )

                # Validate every field in the draft.
                coerced, errors = self._validate_draft(draft_changes)
                if errors:
                    # Back to collecting so the user can fix.
                    draft["state"] = DraftState.COLLECTING.value
                    error_msg = "Some values need fixing:\n" + "\n".join(
                        f"• {e}" for e in errors
                    )
                    return ProfileUpdateChatResponse(
                        reply=error_msg,
                        state=DraftState.COLLECTING.value,
                        draft_changes=draft_changes,
                    )

                # All valid — apply in one transaction.
                draft["state"] = DraftState.APPLYING.value
                try:
                    await self._apply_draft_batch(patient_id, coerced)
                except Exception:
                    logger.exception(
                        "Failed to apply draft for patient %s", patient_id
                    )
                    draft["state"] = DraftState.COLLECTING.value
                    return ProfileUpdateChatResponse(
                        reply="Something went wrong while saving your changes. Please try confirming again.",
                        state=DraftState.COLLECTING.value,
                        draft_changes=draft_changes,
                    )

                # Success!
                draft["state"] = DraftState.COMPLETED.value
                draft["status"] = "completed"
                applied = {
                    k: str(v) for k, v in coerced.items()
                }
                labels = UpdatableField.human_labels()
                field_list = ", ".join(
                    f"{labels.get(f, f)}" for f in applied
                )
                return ProfileUpdateChatResponse(
                    reply=f"Done! Updated: {field_list}.",
                    state=DraftState.COMPLETED.value,
                    draft_changes=None,
                    applied_changes=applied,
                )

            # signal == _SIG_CONTINUE — user made edits while reviewing.
            # Go back to collecting so they can keep editing.
            draft["state"] = DraftState.COLLECTING.value
            reply = llm_reply or "Draft updated. Let me know when you're ready to confirm."
            return ProfileUpdateChatResponse(
                reply=reply,
                state=DraftState.COLLECTING.value,
                draft_changes=draft_changes if draft_changes else None,
            )

        # Fallback — should not be reachable.
        return ProfileUpdateChatResponse(
            reply="Something went wrong. Please start a new request.",
            state=DraftState.COLLECTING.value,
        )

    # ═══════════════════════════════════════════════════════════════════════
    #  Draft reducer (pure function — no I/O)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _reduce_draft(
        draft_changes: Dict[str, str],
        actions: List[LLMAction],
    ) -> Tuple[Dict[str, str], str]:
        """Apply a list of LLM actions to the draft and return
        ``(updated_draft, signal)``.

        Signals: ``"continue"`` (keep collecting), ``"review"`` (user wants
        to confirm), ``"cancel"`` (user wants to cancel everything).
        """
        signal = _SIG_CONTINUE

        for act in actions:
            atype = act.action

            if atype == "set":
                field = act.field
                if field and field in _VALID_FIELDS and act.value is not None:
                    draft_changes[field] = act.value

            elif atype == "remove":
                field = act.field
                if field:
                    draft_changes.pop(field, None)

            elif atype == "confirm_all":
                signal = _SIG_REVIEW

            elif atype == "cancel_all":
                draft_changes.clear()
                signal = _SIG_CANCEL

            # "show_draft" — no mutation, just continue (the LLM reply
            # will already describe the draft).

        return draft_changes, signal

    # ═══════════════════════════════════════════════════════════════════════
    #  Profile context for LLM
    # ═══════════════════════════════════════════════════════════════════════

    @with_postgres_session
    async def _fetch_profile_context(
        self,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[str]:
        """Fetch the patient's current profile and return a JSON string
        for LLM context.  Returns *None* on failure so the agent degrades
        gracefully."""
        try:
            from lib.schemas.patient import CorePatientProfile

            patient = await self.patient_profile_service.fetch_patient_profile(
                patient_id, detailed=True, postgres_session=postgres_session
            )
            profile_data = CorePatientProfile.from_orm(patient).model_dump(
                mode="json"
            )

            updatable_keys = _VALID_FIELDS
            nested_keys = {
                "daily_activity", "alcohol_consumption", "smoking_habit",
                "eating_habit", "sleep_habit", "diabetic_history",
                "current_medication", "food_allergies", "drug_allergies",
                "medical_histories",
            }
            relevant_keys = updatable_keys | nested_keys
            filtered = {
                k: v for k, v in profile_data.items() if k in relevant_keys
            }

            return json.dumps(filtered, indent=2, default=str)
        except Exception:
            logger.warning(
                "Failed to fetch profile context for patient %s",
                patient_id,
                exc_info=True,
            )
            return None

    # ═══════════════════════════════════════════════════════════════════════
    #  LLM intent extraction
    # ═══════════════════════════════════════════════════════════════════════

    async def _extract_intent(
        self,
        messages: List[Dict[str, str]],
        *,
        profile_context: Optional[str] = None,
    ) -> LLMResponse:
        """Call the LLM to extract structured actions from the conversation."""

        system_content = SYSTEM_PROMPT
        if profile_context:
            system_content += (
                f"\n\n## Patient's current profile\n```json\n{profile_context}\n```"
            )

        llm_messages = [{"role": "system", "content": system_content}] + messages

        try:
            response = await self.openai_client.chat.completions.create(
                model=_LLM_MODEL,
                messages=llm_messages,
                temperature=0.0,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            raw = json.loads(content)

            # Parse into our Pydantic model, tolerating partial data.
            actions_raw = raw.get("actions", [])
            actions: List[LLMAction] = []
            for a in actions_raw:
                try:
                    actions.append(LLMAction(**a))
                except Exception:
                    logger.debug("Skipping invalid LLM action: %s", a)

            return LLMResponse(
                actions=actions,
                reply=raw.get("reply", ""),
            )

        except json.JSONDecodeError:
            logger.warning(
                "LLM returned non-JSON response; falling back to empty intent."
            )
            return LLMResponse(
                reply="Sorry, I didn't quite catch that. Could you rephrase?"
            )
        except Exception:
            logger.exception("OpenAI call failed during profile-update agent chat.")
            return LLMResponse(
                reply="I'm having trouble processing your request right now. Please try again shortly."
            )

    # ═══════════════════════════════════════════════════════════════════════
    #  Validation & coercion
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _validate_draft(
        draft_changes: Dict[str, str],
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Validate + coerce every field in the draft.

        Returns ``(coerced_map, errors)`` — if ``errors`` is non-empty, no
        DB write should happen.
        """
        coerced: Dict[str, Any] = {}
        errors: List[str] = []
        labels = UpdatableField.human_labels()

        for field, raw_value in draft_changes.items():
            try:
                coerced[field] = ProfileUpdateAgentService._coerce_value(
                    field, raw_value
                )
            except ValueError as exc:
                errors.append(f"{labels.get(field, field)}: {exc}")

        return coerced, errors

    @staticmethod
    def _coerce_value(field: str, raw_value: str) -> Any:
        """Convert the string value from the LLM into the Python type
        expected by the Patient model.

        Raises ``ValueError`` with a user-friendly message when validation
        fails — the caller surfaces this to the patient.
        """

        # ── Numeric fields ──────────────────────────────────────────────────
        if field == "height":
            try:
                v = float(raw_value)
            except (ValueError, TypeError):
                raise ValueError(
                    "Height must be a number (in cm). Please provide a valid value."
                )
            if not (30 <= v <= 300):
                raise ValueError(
                    "Height should be between 30 and 300 cm. Please try again."
                )
            return v

        if field == "weight":
            try:
                v = float(raw_value)
            except (ValueError, TypeError):
                raise ValueError(
                    "Weight must be a number (in kg). Please provide a valid value."
                )
            if not (1 <= v <= 500):
                raise ValueError(
                    "Weight should be between 1 and 500 kg. Please try again."
                )
            return v

        if field == "waist":
            try:
                v = float(raw_value)
            except (ValueError, TypeError):
                raise ValueError(
                    "Waist must be a number (in cm). Please provide a valid value."
                )
            if not (20 <= v <= 300):
                raise ValueError(
                    "Waist should be between 20 and 300 cm. Please try again."
                )
            return v

        # ── Date ────────────────────────────────────────────────────────────
        if field == "dob":
            try:
                return _date.fromisoformat(raw_value)
            except (ValueError, TypeError):
                raise ValueError(
                    "Date of birth must be in YYYY-MM-DD format. Please try again."
                )

        # ── Gender ──────────────────────────────────────────────────────────
        if field == "gender":
            normalised = raw_value.strip().lower()
            if normalised not in _VALID_GENDERS:
                raise ValueError(
                    f"Gender must be one of: {', '.join(sorted(_VALID_GENDERS))}."
                )
            return normalised

        # ── Email ───────────────────────────────────────────────────────────
        if field == "email":
            email = raw_value.strip().lower()
            if not _EMAIL_RE.match(email):
                raise ValueError(
                    "That doesn't look like a valid email address. Please try again."
                )
            return email

        # ── Activity level ──────────────────────────────────────────────────
        if field == "activity_level":
            normalised = raw_value.strip().lower().replace(" ", "_")
            if normalised not in _VALID_ACTIVITY_LEVELS:
                raise ValueError(
                    f"Activity level must be one of: {', '.join(sorted(_VALID_ACTIVITY_LEVELS))}."
                )
            return normalised

        # ── Sleep quality ───────────────────────────────────────────────────
        if field == "sleep_quality":
            normalised = raw_value.strip().lower()
            if normalised not in _VALID_SLEEP_QUALITIES:
                raise ValueError(
                    f"Sleep quality must be one of: {', '.join(sorted(_VALID_SLEEP_QUALITIES))}."
                )
            return normalised

        # ── Boolean fields ──────────────────────────────────────────────────
        if field in ("consume_alcohol", "smoke_status", "has_medication"):
            normalised = raw_value.strip().lower()
            if normalised in _BOOL_TRUE:
                return True
            if normalised in _BOOL_FALSE:
                return False
            raise ValueError("Please answer with 'yes' or 'no'.")

        # ── Integer fields ──────────────────────────────────────────────────
        if field in ("meals_per_day", "snacks_count"):
            try:
                v = int(raw_value)
            except (ValueError, TypeError):
                raise ValueError(
                    f"{UpdatableField.human_labels().get(field, field)} must be a whole number."
                )
            if not (0 <= v <= 10):
                raise ValueError(
                    f"{UpdatableField.human_labels().get(field, field)} should be between 0 and 10."
                )
            return v

        # ── List fields (comma-separated) ───────────────────────────────────
        if field in ("food_allergies", "drug_allergies", "medical_conditions"):
            items = [item.strip() for item in raw_value.split(",") if item.strip()]
            if not items:
                raise ValueError(
                    "Please provide at least one item (comma-separated for multiple)."
                )
            return items

        # ── Fallback (string fields: first_name, last_name, locale, etc.) ──
        return raw_value

    # ═══════════════════════════════════════════════════════════════════════
    #  Batch persistence (single transaction)
    # ═══════════════════════════════════════════════════════════════════════

    @with_postgres_session
    async def _apply_draft_batch(
        self,
        patient_id: str,
        coerced_changes: Dict[str, Any],
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Apply **all** approved draft changes in a single Postgres
        transaction.  If anything fails the transaction is rolled back and
        nothing is persisted."""

        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id, detailed=True, postgres_session=postgres_session
        )

        sections_touched: set[str] = set()

        for field, value in coerced_changes.items():
            section = FIELD_TO_SECTION.get(field, "basic")
            sections_touched.add(section)

            if section == "basic":
                self._mutate_basic_field(patient, field, value)
            elif section == "lifestyle":
                self._mutate_lifestyle_field(patient, patient_id, field, value)
            elif section == "medical_history":
                self._mutate_medical_history_field(
                    patient, patient_id, field, value
                )

        # Mark touched sections as complete.
        for section in sections_touched:
            self._mark_profile_section_complete(patient, section)

        postgres_session.add(patient)
        await postgres_session.commit()

        logger.info(
            "Draft batch applied for patient %s — fields: %s",
            patient_id,
            ", ".join(coerced_changes.keys()),
        )

        # ── Post-commit side effects ───────────────────────────────────────
        # Fire-and-forget; failures here must not undo the committed write.
        try:
            await self.patient_profile_service.chat_notification_service.notify_participants(
                message_key="chat_list_updated",
                user_id=patient_id,
            )
        except Exception:
            logger.warning(
                "Failed to send chat notification after batch apply for %s",
                patient_id,
                exc_info=True,
            )

        if sections_touched & {"basic"}:
            try:
                from lib.schemas.patient import CorePatientProfile
                from lib.workers.tasks.profile.enqueue import (
                    enqueue_generate_profile_vector_sync,
                )

                # Refresh to get the fully committed state.
                await postgres_session.refresh(patient)
                detailed = await self.patient_profile_service.fetch_patient_profile(
                    patient_id, detailed=True, postgres_session=postgres_session
                )
                profile_data = CorePatientProfile.from_orm(detailed).model_dump(
                    mode="json"
                )
                enqueue_generate_profile_vector_sync(patient_id, profile_data)
            except Exception:
                logger.warning(
                    "Failed to enqueue vector sync after batch apply for %s",
                    patient_id,
                    exc_info=True,
                )

    # ── Pure ORM mutators (no commit, no session) ──────────────────────────

    @staticmethod
    def _mutate_basic_field(
        patient: PatientModel, field: str, value: Any
    ) -> None:
        """Set a single column on the Patient ORM object."""
        if field not in ("created_at", "updated_at", "phone_number"):
            setattr(patient, field, value)

    @staticmethod
    def _mutate_lifestyle_field(
        patient: PatientModel,
        patient_id: str,
        field: str,
        value: Any,
    ) -> None:
        """Mutate a lifestyle child model on the patient ORM object."""

        if field == "activity_level":
            if patient.daily_activity:
                patient.daily_activity.activity_level = value
            else:
                patient.daily_activity = PatientDailyActivityModel(
                    patient_id=patient_id, activity_level=value
                )

        elif field == "consume_alcohol":
            if patient.alcohol_consumption:
                patient.alcohol_consumption.consume_alcohol = value
            else:
                patient.alcohol_consumption = PatientAlcoholConsumptionModel(
                    patient_id=patient_id, consume_alcohol=value
                )

        elif field == "smoke_status":
            if patient.smoking_habit:
                patient.smoking_habit.smoke_status = value
            else:
                patient.smoking_habit = PatientSmokingHabitModel(
                    patient_id=patient_id, smoke_status=value
                )

        elif field == "sleep_quality":
            if patient.sleep_habit:
                patient.sleep_habit.sleep_quality = value
            else:
                patient.sleep_habit = PatientSleepHabitModel(
                    patient_id=patient_id, sleep_quality=value
                )

        elif field == "meals_per_day":
            if patient.eating_habit:
                patient.eating_habit.meals_per_day = value
            else:
                patient.eating_habit = PatientEatingHabitModel(
                    patient_id=patient_id, meals_per_day=value
                )

        elif field == "snacks_count":
            if patient.eating_habit:
                patient.eating_habit.snacks_count = value
            else:
                patient.eating_habit = PatientEatingHabitModel(
                    patient_id=patient_id, snacks_count=value
                )

        elif field == "food_allergies":
            patient.food_allergies = [
                PatientFoodAllergyModel(patient_id=patient_id, allergy_name=name)
                for name in value
            ]

    @staticmethod
    def _mutate_medical_history_field(
        patient: PatientModel,
        patient_id: str,
        field: str,
        value: Any,
    ) -> None:
        """Mutate a medical-history child model on the patient ORM object."""

        if field == "type_of_diabetes":
            if patient.diabetic_history:
                patient.diabetic_history.type_of_diabetes = value
            else:
                patient.diabetic_history = PatientDiabeticHistoryModel(
                    patient_id=patient_id, type_of_diabetes=value
                )

        elif field == "drug_allergies":
            patient.drug_allergies = [
                PatientDrugAllergyModel(patient_id=patient_id, allergy_name=name)
                for name in value
            ]

        elif field == "medical_conditions":
            patient.medical_histories = [
                PatientMedicalHistoryModel(
                    patient_id=patient_id, condition=name, duration_years=0
                )
                for name in value
            ]

    # ── profile_completion helper ───────────────────────────────────────────
    @staticmethod
    def _mark_profile_section_complete(
        patient: PatientModel, section: str
    ) -> None:
        """Flip ``is_complete`` for a profile_completion section."""
        pc = patient.profile_completion
        if pc and not pc.get(section, {}).get("is_complete"):
            pc[section]["is_complete"] = True
            flag_modified(patient, "profile_completion")

    # ── Review summary builder ──────────────────────────────────────────────
    @staticmethod
    def _build_review_summary(draft_changes: Dict[str, str]) -> str:
        """Generate a human-readable summary of the pending draft."""
        labels = UpdatableField.human_labels()
        lines = [
            f"• {labels.get(f, f)} → {v}" for f, v in draft_changes.items()
        ]
        summary = "Here's what I'll update:\n" + "\n".join(lines)
        summary += "\n\nShall I confirm all these changes?"
        return summary

    # ═══════════════════════════════════════════════════════════════════════
    #  Mongo helpers
    # ═══════════════════════════════════════════════════════════════════════

    async def _get_or_create_draft(
        self, patient_id: str
    ) -> Dict[str, Any]:
        """Return the active draft for *patient_id*, creating one if none
        exists."""

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
            # Race condition — another request created the draft first.
            doc = await self.conversation_collection.find_one(
                {"patient_id": patient_id, "status": "active"}
            )
            if doc:
                return doc
        return new_doc

    async def _save_draft(self, draft: Dict[str, Any]) -> None:
        """Persist the draft back to Mongo."""
        draft["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.conversation_collection.replace_one(
            {"patient_id": draft["patient_id"], "status": "active"},
            draft,
            upsert=True,
        )