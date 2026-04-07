"""Profile Update micro-agent service.

Manages a short multi-turn conversation to update a single profile field,
backed by Mongo for conversation state and Postgres (via PatientProfileService)
for the actual write.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date as _date
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorCollection
from openai import AsyncOpenAI
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
from lib.schemas.patient import PatientUpdate
from lib.schemas.profile_update_agent import (
    BASIC_FIELDS,
    FIELD_TO_SECTION,
    LIFESTYLE_FIELDS,
    MEDICAL_HISTORY_FIELDS,
    ConversationListResponse,
    ConversationState,
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


class ProfileUpdateAgentService:
    """Lightweight conversational agent for profile updates.

    Design decisions:
    * One Mongo document per conversation, keyed by ``conversation_id``.
    * FSM states live in ``ConversationState``; transitions happen in
      ``_advance_state``.
    * The LLM is only used for *intent extraction* — all mutation logic is
      deterministic so it can be tested / audited without an LLM in the loop.
    * ``PatientProfileService.update_basic_patient_profile`` is reused for
      basic-section writes, preserving existing validation, events, and vector
      store sync.
    * Lifestyle and medical-history fields are written directly via the ORM
      with ``profile_completion`` flags updated accordingly.
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

    # ── Public entry-point ──────────────────────────────────────────────────
    async def chat(
        self,
        patient_id: str,
        message: str,
        conversation_id: Optional[str] = None,
    ) -> ProfileUpdateChatResponse:
        """Process a single user turn and return the agent's reply."""

        # 1. Load or create conversation
        conv = await self._get_or_create_conversation(
            patient_id, conversation_id
        )
        conv_id: str = conv["conversation_id"]

        # 2. Append user message to history
        conv["messages"].append({"role": "user", "content": message})

        # 3. Ask the LLM to extract intent
        parsed = await self._extract_intent(conv["messages"])

        # 4. Advance FSM and build reply
        response = await self._advance_state(conv, parsed, patient_id)

        # 5. Append assistant reply to history and persist
        conv["messages"].append({"role": "assistant", "content": response.reply})
        await self._save_conversation(conv)

        return response

    # ── List conversations ──────────────────────────────────────────────────
    async def list_conversations(
        self,
        patient_id: str,
        limit: int = 20,
        skip: int = 0,
    ) -> List[ConversationListResponse]:
        """Return a paginated list of conversation summaries for a patient."""

        cursor = (
            self.conversation_collection.find(
                {"patient_id": patient_id},
                {
                    "conversation_id": 1,
                    "state": 1,
                    "target_field": 1,
                    "created_at": 1,
                    "updated_at": 1,
                    "messages": 1,
                    "_id": 0,
                },
            )
            .sort("updated_at", -1)
            .skip(skip)
            .limit(limit)
        )

        results: List[ConversationListResponse] = []
        async for doc in cursor:
            results.append(
                ConversationListResponse(
                    conversation_id=doc["conversation_id"],
                    state=doc.get("state", ConversationState.IDLE.value),
                    target_field=doc.get("target_field"),
                    created_at=doc.get("created_at"),
                    updated_at=doc.get("updated_at"),
                    message_count=len(doc.get("messages", [])),
                )
            )
        return results

    # ── FSM logic ───────────────────────────────────────────────────────────
    async def _advance_state(
        self,
        conv: Dict[str, Any],
        parsed: Dict[str, Any],
        patient_id: str,
    ) -> ProfileUpdateChatResponse:
        """Deterministic state-machine that decides what to do next."""

        state = ConversationState(conv.get("state", ConversationState.IDLE.value))
        field_from_llm = parsed.get("field")
        value_from_llm = parsed.get("value")
        confirmation = parsed.get("confirmation")
        llm_reply: str = parsed.get("reply", "")
        conv_id: str = conv["conversation_id"]

        # Helper: valid field?
        valid_fields = {f.value for f in UpdatableField}

        # ── IDLE / AWAITING_FIELD ───────────────────────────────────────────
        if state in (ConversationState.IDLE, ConversationState.AWAITING_FIELD):
            if field_from_llm and field_from_llm in valid_fields:
                conv["target_field"] = field_from_llm

                if value_from_llm:
                    # User provided both field + value in one shot
                    conv["target_value"] = value_from_llm
                    conv["state"] = ConversationState.AWAITING_CONFIRMATION.value
                    human_label = UpdatableField.human_labels().get(
                        field_from_llm, field_from_llm
                    )
                    reply = (
                        f"I'll update your {human_label} to '{value_from_llm}'. "
                        "Shall I go ahead?"
                    )
                else:
                    conv["state"] = ConversationState.AWAITING_VALUE.value
                    reply = llm_reply or (
                        f"What would you like your new "
                        f"{UpdatableField.human_labels().get(field_from_llm, field_from_llm)} to be?"
                    )
            else:
                conv["state"] = ConversationState.AWAITING_FIELD.value
                reply = llm_reply or (
                    "Which field would you like to update? "
                    f"You can choose from: {UpdatableField.list_for_prompt()}."
                )

            return ProfileUpdateChatResponse(
                conversation_id=conv_id,
                reply=reply,
                state=conv["state"],
            )

        # ── AWAITING_VALUE ──────────────────────────────────────────────────
        if state == ConversationState.AWAITING_VALUE:
            if value_from_llm:
                conv["target_value"] = value_from_llm
                conv["state"] = ConversationState.AWAITING_CONFIRMATION.value
                human_label = UpdatableField.human_labels().get(
                    conv["target_field"], conv["target_field"]
                )
                reply = (
                    f"I'll update your {human_label} to '{value_from_llm}'. "
                    "Shall I go ahead?"
                )
            else:
                reply = llm_reply or "Please provide the new value."

            return ProfileUpdateChatResponse(
                conversation_id=conv_id,
                reply=reply,
                state=conv["state"],
            )

        # ── AWAITING_CONFIRMATION ───────────────────────────────────────────
        if state == ConversationState.AWAITING_CONFIRMATION:
            if confirmation is True:
                target_field = conv["target_field"]
                target_value = conv["target_value"]

                # Validate & coerce — on failure, ask for the value again.
                try:
                    coerced_value = self._coerce_value(target_field, target_value)
                except ValueError as exc:
                    conv["state"] = ConversationState.AWAITING_VALUE.value
                    conv["target_value"] = None
                    return ProfileUpdateChatResponse(
                        conversation_id=conv_id,
                        reply=str(exc),
                        state=conv["state"],
                    )

                # Perform the actual update
                await self._apply_update(patient_id, target_field, coerced_value)

                conv["state"] = ConversationState.COMPLETED.value
                human_label = UpdatableField.human_labels().get(
                    target_field, target_field
                )
                reply = (
                    f"Done! Your {human_label} has been updated to '{target_value}'."
                )

                return ProfileUpdateChatResponse(
                    conversation_id=conv_id,
                    reply=reply,
                    state=conv["state"],
                    updated_field=target_field,
                    updated_value=target_value,
                )
            elif confirmation is False:
                # User declined — reset to idle
                conv["state"] = ConversationState.IDLE.value
                conv["target_field"] = None
                conv["target_value"] = None
                reply = (
                    "No problem, the update has been cancelled. "
                    "Is there anything else you'd like to change?"
                )
                return ProfileUpdateChatResponse(
                    conversation_id=conv_id,
                    reply=reply,
                    state=conv["state"],
                )
            else:
                reply = llm_reply or "Please confirm — shall I go ahead with the update? (yes / no)"
                return ProfileUpdateChatResponse(
                    conversation_id=conv_id,
                    reply=reply,
                    state=conv["state"],
                )

        # ── COMPLETED (user keeps talking after a successful update) ────────
        # Reset so they can start another update in the same conversation.
        conv["state"] = ConversationState.IDLE.value
        conv["target_field"] = None
        conv["target_value"] = None
        return await self._advance_state(conv, parsed, patient_id)

    # ── LLM intent extraction ──────────────────────────────────────────────
    async def _extract_intent(
        self, messages: list[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Call the LLM to extract field, value, confirmation from the
        conversation history.  Falls back gracefully on parse errors."""

        llm_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        try:
            response = await self.openai_client.chat.completions.create(
                model=_LLM_MODEL,
                messages=llm_messages,
                temperature=0.0,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning(
                "LLM returned non-JSON response; falling back to empty intent."
            )
            return {"reply": "Sorry, I didn't quite catch that. Could you rephrase?"}
        except Exception:
            logger.exception("OpenAI call failed during profile-update agent chat.")
            return {
                "reply": "I'm having trouble processing your request right now. Please try again shortly."
            }

    # ── Dispatcher — routes to the correct write path ──────────────────────
    async def _apply_update(
        self, patient_id: str, field: str, value: Any
    ) -> None:
        """Route the update to the correct persistence method based on the
        field's profile section."""

        section = FIELD_TO_SECTION.get(field, "basic")

        if section == "basic":
            await self._apply_basic_update(patient_id, field, value)
        elif section == "lifestyle":
            await self._apply_lifestyle_update(patient_id, field, value)
        elif section == "medical_history":
            await self._apply_medical_history_update(patient_id, field, value)
        else:
            logger.error("Unknown section '%s' for field '%s'", section, field)

    # ── Basic write (delegates to existing service) ─────────────────────────
    async def _apply_basic_update(
        self, patient_id: str, field: str, value: Any
    ) -> None:
        """Build a ``PatientUpdate`` with a single field and delegate to
        ``PatientProfileService``."""

        update_data = PatientUpdate.model_construct(
            **{field: value, "phone_number": ""}
        )
        update_data.model_fields_set.add(field)

        await self.patient_profile_service.update_basic_patient_profile(
            patient_id=patient_id,
            patient_data=update_data,
        )
        logger.info(
            "Profile field '%s' updated for patient %s", field, patient_id
        )

    # ── Lifestyle write (per-field ORM update) ──────────────────────────────
    @with_postgres_session
    async def _apply_lifestyle_update(
        self,
        patient_id: str,
        field: str,
        value: Any,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Update a single lifestyle-related child model and mark the
        lifestyle section of ``profile_completion`` as complete."""

        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id, detailed=True, postgres_session=postgres_session
        )

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
            # value is a List[str] — replace existing list
            new_allergies = [
                PatientFoodAllergyModel(patient_id=patient_id, allergy_name=name)
                for name in value
            ]
            patient.food_allergies = new_allergies

        self._mark_profile_section_complete(patient, "lifestyle")

        postgres_session.add(patient)
        await postgres_session.commit()
        logger.info(
            "Lifestyle field '%s' updated for patient %s", field, patient_id
        )

    # ── Medical-history write (per-field ORM update) ────────────────────────
    @with_postgres_session
    async def _apply_medical_history_update(
        self,
        patient_id: str,
        field: str,
        value: Any,
        *,
        postgres_session: AsyncSession,
    ) -> None:
        """Update a single medical-history child model and mark the
        medical_history section of ``profile_completion`` as complete."""

        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id, detailed=True, postgres_session=postgres_session
        )

        if field == "type_of_diabetes":
            if patient.diabetic_history:
                patient.diabetic_history.type_of_diabetes = value
            else:
                patient.diabetic_history = PatientDiabeticHistoryModel(
                    patient_id=patient_id, type_of_diabetes=value
                )

        elif field == "drug_allergies":
            # value is a List[str] — replace existing list
            new_allergies = [
                PatientDrugAllergyModel(patient_id=patient_id, allergy_name=name)
                for name in value
            ]
            patient.drug_allergies = new_allergies

        elif field == "medical_conditions":
            # value is a List[str] — replace existing list
            new_conditions = [
                PatientMedicalHistoryModel(
                    patient_id=patient_id, condition=name, duration_years=0
                )
                for name in value
            ]
            patient.medical_histories = new_conditions

        self._mark_profile_section_complete(patient, "medical_history")

        postgres_session.add(patient)
        await postgres_session.commit()
        logger.info(
            "Medical-history field '%s' updated for patient %s",
            field,
            patient_id,
        )

    # ── profile_completion helper ───────────────────────────────────────────
    @staticmethod
    def _mark_profile_section_complete(patient: PatientModel, section: str) -> None:
        """Flip the ``is_complete`` flag on a profile_completion section and
        tell SQLAlchemy the JSON column was mutated."""
        pc = patient.profile_completion
        if pc and not pc.get(section, {}).get("is_complete"):
            pc[section]["is_complete"] = True
            flag_modified(patient, "profile_completion")

    # ── Value coercion & validation ─────────────────────────────────────────
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
            raise ValueError(
                "Please answer with 'yes' or 'no'."
            )

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

    # ── Mongo helpers ───────────────────────────────────────────────────────
    async def _get_or_create_conversation(
        self, patient_id: str, conversation_id: Optional[str]
    ) -> Dict[str, Any]:
        if conversation_id:
            doc = await self.conversation_collection.find_one(
                {"conversation_id": conversation_id, "patient_id": patient_id}
            )
            if doc:
                return doc
            logger.warning(
                "Conversation %s not found for patient %s — creating new one.",
                conversation_id,
                patient_id,
            )

        now = datetime.now(timezone.utc).isoformat()
        new_doc: Dict[str, Any] = {
            "conversation_id": uuid4().hex,
            "patient_id": patient_id,
            "state": ConversationState.IDLE.value,
            "target_field": None,
            "target_value": None,
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }
        await self.conversation_collection.insert_one(new_doc)
        return new_doc

    async def _save_conversation(self, conv: Dict[str, Any]) -> None:
        conv["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.conversation_collection.replace_one(
            {"conversation_id": conv["conversation_id"]}, conv, upsert=True
        )
