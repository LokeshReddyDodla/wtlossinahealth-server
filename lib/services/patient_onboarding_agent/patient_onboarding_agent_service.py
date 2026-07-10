"""Conversational patient onboarding service with guided questions."""

from __future__ import annotations

import json
import logging
import re
from datetime import date as _date
from datetime import datetime, time as _time, timezone
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
from lib.schemas.patient import CorePatientProfile
from lib.schemas.patient_onboarding_agent import (
    FIELD_TO_SECTION,
    QUESTION_ORDER,
    REQUIRED_FIELDS,
    LLMAction,
    LLMResponse,
    OnboardingField,
    OnboardingSessionSummaryResponse,
    OnboardingState,
    PatientOnboardingChatResponse,
)
from lib.services.patient_onboarding_agent.prompts import build_system_prompt
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.workers.tasks.profile.enqueue import enqueue_generate_profile_vector_async

logger = logging.getLogger(__name__)

_LLM_MODEL = "gpt-4o-mini"

_VALID_FIELDS = {field.value for field in OnboardingField}
_VALID_GENDERS = {"male", "female", "other"}
_VALID_ACTIVITY_LEVELS = {"sedentary", "light", "moderate", "active", "very_active"}
_VALID_SLEEP_QUALITIES = {"good", "average", "poor"}
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
_BOOL_TRUE = {"yes", "true", "1", "y"}
_BOOL_FALSE = {"no", "false", "0", "n"}
_CONFIRM_TERMS = {
    "yes",
    "confirm",
    "confirmed",
    "looks good",
    "go ahead",
    "save it",
    "proceed",
}
_EDIT_TERMS = {"no", "not yet", "change", "edit"}

_SECTION_REQUIRED_FIELDS: Dict[str, List[str]] = {
    "basic": [
        OnboardingField.FIRST_NAME.value,
        OnboardingField.LAST_NAME.value,
        OnboardingField.EMAIL.value,
        OnboardingField.DOB.value,
        OnboardingField.GENDER.value,
        OnboardingField.HEIGHT.value,
        OnboardingField.WEIGHT.value,
        OnboardingField.WAIST.value,
    ],
    "lifestyle": [
        OnboardingField.ACTIVITY_LEVEL.value,
        OnboardingField.CONSUME_ALCOHOL.value,
        OnboardingField.SMOKE_STATUS.value,
        OnboardingField.SLEEP_QUALITY.value,
        OnboardingField.MEALS_PER_DAY.value,
        OnboardingField.SNACKS_COUNT.value,
    ],
    "medical_history": [
        OnboardingField.TYPE_OF_DIABETES.value,
        OnboardingField.HAS_MEDICATION.value,
    ],
}

_QUESTION_PROMPTS: Dict[str, str] = {
    OnboardingField.FIRST_NAME.value: "What is your first name?",
    OnboardingField.LAST_NAME.value: "What is your last name?",
    OnboardingField.EMAIL.value: "What email address should we use for your account?",
    OnboardingField.DOB.value: "What is your date of birth? Please use YYYY-MM-DD if possible.",
    OnboardingField.GENDER.value: "What is your gender? Please answer male, female, or other.",
    OnboardingField.HEIGHT.value: "What is your height in centimeters?",
    OnboardingField.WEIGHT.value: "What is your weight in kilograms?",
    OnboardingField.WAIST.value: "What is your waist measurement in centimeters?",
    OnboardingField.ACTIVITY_LEVEL.value: (
        "How active are you on most days? "
        "Please answer sedentary, light, moderate, active, or very active."
    ),
    OnboardingField.CONSUME_ALCOHOL.value: "Do you currently drink alcohol? Please answer yes or no.",
    OnboardingField.SMOKE_STATUS.value: "Do you currently smoke? Please answer yes or no.",
    OnboardingField.SLEEP_QUALITY.value: "How would you describe your sleep quality: good, average, or poor?",
    OnboardingField.MEALS_PER_DAY.value: "How many meals do you usually eat per day?",
    OnboardingField.SNACKS_COUNT.value: "How many snacks do you usually have per day?",
    OnboardingField.TYPE_OF_DIABETES.value: "What type of diabetes do you have? If none, say none.",
    OnboardingField.HAS_MEDICATION.value: "Are you currently taking any medication? Please answer yes or no.",
}


class PatientOnboardingAgentService:
    """Guided onboarding agent that asks for required fields sequentially."""

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
        self._indexes_ensured = False

    async def ensure_indexes(self) -> None:
        await self.conversation_collection.create_index(
            [("patient_id", 1)],
            unique=True,
            partialFilterExpression={"status": "active"},
            name="unique_active_onboarding_session_per_patient",
        )

    async def start(
        self,
        patient_id: str,
        *,
        restart: bool = False,
    ) -> PatientOnboardingChatResponse:
        await self._ensure_indexes_once()
        existing_answers = await self._load_existing_answers(patient_id)
        missing = self._compute_missing_required_fields(
            existing_answers, {}
        )
        if not missing and not restart:
            return PatientOnboardingChatResponse(
                reply=(
                    "Your onboarding profile is already complete. "
                    "Use the profile update agent if you want to make changes."
                ),
                state=OnboardingState.COMPLETED.value,
                current_question_field=None,
                missing_required_fields=[],
                draft_changes=None,
            )

        session = await self._get_or_create_session(patient_id)
        if restart or session.get("state") in (
            OnboardingState.COMPLETED.value,
            OnboardingState.CANCELLED.value,
        ):
            session = self._reset_session(patient_id)

        combined_missing = self._compute_missing_required_fields(
            existing_answers,
            session.get("draft_changes", {}),
        )
        if not combined_missing:
            session["state"] = OnboardingState.REVIEWING.value
            session["current_question_field"] = None
            await self._save_session(session)
            return PatientOnboardingChatResponse(
                reply=self._build_review_summary(
                    existing_answers, session.get("draft_changes", {})
                ),
                state=OnboardingState.REVIEWING.value,
                current_question_field=None,
                missing_required_fields=[],
                draft_changes=session.get("draft_changes") or None,
            )

        current_field = session.get("current_question_field")
        if current_field not in combined_missing:
            current_field = combined_missing[0]
            session["current_question_field"] = current_field
        session["state"] = OnboardingState.COLLECTING.value
        await self._save_session(session)

        return PatientOnboardingChatResponse(
            reply=(
                "I'll guide you through your onboarding profile one step at a time.\n\n"
                + self._question_for_field(current_field)
            ),
            state=OnboardingState.COLLECTING.value,
            current_question_field=current_field,
            missing_required_fields=combined_missing,
            draft_changes=session.get("draft_changes") or None,
        )

    async def chat(
        self,
        patient_id: str,
        message: str,
    ) -> PatientOnboardingChatResponse:
        await self._ensure_indexes_once()
        clean_message = (message or "").strip()
        if not clean_message:
            return await self.start(patient_id)

        existing_answers = await self._load_existing_answers(patient_id)
        missing_before = self._compute_missing_required_fields(
            existing_answers, {}
        )
        if not missing_before:
            return PatientOnboardingChatResponse(
                reply=(
                    "Your onboarding profile is already complete. "
                    "Use the profile update agent if you want to make changes."
                ),
                state=OnboardingState.COMPLETED.value,
                current_question_field=None,
                missing_required_fields=[],
                draft_changes=None,
            )

        session = await self._get_or_create_session(patient_id)
        if session.get("state") == OnboardingState.COMPLETED.value:
            return PatientOnboardingChatResponse(
                reply=(
                    "Your onboarding session is already complete. "
                    "Use the profile update agent if you want to update anything."
                ),
                state=OnboardingState.COMPLETED.value,
                current_question_field=None,
                missing_required_fields=[],
                draft_changes=None,
            )

        session["messages"].append({"role": "user", "content": clean_message})
        parsed = self._parse_review_shortcuts(session, clean_message)
        if parsed is None:
            parsed = await self._extract_intent(
                messages=session["messages"],
                current_field=session.get("current_question_field"),
                missing_required_fields=self._compute_missing_required_fields(
                    existing_answers, session.get("draft_changes", {})
                ),
            )

        response = await self._advance_state(
            session=session,
            parsed=parsed,
            patient_id=patient_id,
            existing_answers=existing_answers,
            raw_message=clean_message,
        )
        session["messages"].append({"role": "assistant", "content": response.reply})
        await self._save_session(session)
        return response

    async def get_active_session(
        self,
        patient_id: str,
    ) -> Optional[OnboardingSessionSummaryResponse]:
        await self._ensure_indexes_once()
        doc = await self.conversation_collection.find_one(
            {"patient_id": patient_id, "status": "active"}
        )
        if not doc:
            return None

        existing_answers = await self._load_existing_answers(patient_id)
        missing = self._compute_missing_required_fields(
            existing_answers, doc.get("draft_changes", {})
        )
        return OnboardingSessionSummaryResponse(
            state=doc.get("state", OnboardingState.COLLECTING.value),
            current_question_field=doc.get("current_question_field"),
            missing_required_fields=missing,
            draft_changes=doc.get("draft_changes", {}),
            message_count=len(doc.get("messages", [])),
            created_at=doc.get("created_at"),
            updated_at=doc.get("updated_at"),
        )

    async def _advance_state(
        self,
        *,
        session: Dict[str, Any],
        parsed: LLMResponse,
        patient_id: str,
        existing_answers: Dict[str, Any],
        raw_message: str,
    ) -> PatientOnboardingChatResponse:
        state = OnboardingState(
            session.get("state", OnboardingState.COLLECTING.value)
        )
        draft_changes, signal, saved_fields, removed_fields, errors = (
            self._apply_actions_to_draft(
                dict(session.get("draft_changes", {})),
                parsed.actions,
            )
        )
        session["draft_changes"] = draft_changes

        if signal == "cancel":
            session["state"] = OnboardingState.CANCELLED.value
            session["status"] = "cancelled"
            session["current_question_field"] = None
            return PatientOnboardingChatResponse(
                reply="Onboarding cancelled. Start again whenever you're ready.",
                state=OnboardingState.CANCELLED.value,
                current_question_field=None,
                missing_required_fields=self._compute_missing_required_fields(
                    existing_answers, {}
                ),
                draft_changes=None,
            )

        combined_answers = self._merge_answers(existing_answers, draft_changes)
        missing = self._compute_missing_required_fields(existing_answers, draft_changes)

        if state == OnboardingState.REVIEWING:
            if signal == "review":
                if missing:
                    next_field = missing[0]
                    session["state"] = OnboardingState.COLLECTING.value
                    session["current_question_field"] = next_field
                    return PatientOnboardingChatResponse(
                        reply=(
                            "I still need a few required details before I can save this.\n\n"
                            + self._question_for_field(next_field)
                        ),
                        state=OnboardingState.COLLECTING.value,
                        current_question_field=next_field,
                        missing_required_fields=missing,
                        draft_changes=draft_changes or None,
                    )

                session["state"] = OnboardingState.APPLYING.value
                try:
                    await self._apply_draft_batch(patient_id, draft_changes)
                except Exception:
                    logger.exception(
                        "Failed to apply onboarding draft for patient %s",
                        patient_id,
                    )
                    session["state"] = OnboardingState.REVIEWING.value
                    return PatientOnboardingChatResponse(
                        reply="Something went wrong while saving your onboarding answers. Please try confirming again.",
                        state=OnboardingState.REVIEWING.value,
                        current_question_field=None,
                        missing_required_fields=missing,
                        draft_changes=draft_changes or None,
                    )

                session["state"] = OnboardingState.COMPLETED.value
                session["status"] = "completed"
                session["current_question_field"] = None
                return PatientOnboardingChatResponse(
                    reply="Your onboarding profile has been saved successfully.",
                    state=OnboardingState.COMPLETED.value,
                    current_question_field=None,
                    missing_required_fields=[],
                    draft_changes=None,
                    applied_changes=draft_changes,
                )

            if errors:
                next_field = errors[0][0]
                session["state"] = OnboardingState.COLLECTING.value
                session["current_question_field"] = next_field
                return PatientOnboardingChatResponse(
                    reply=self._build_error_question_reply(errors, next_field),
                    state=OnboardingState.COLLECTING.value,
                    current_question_field=next_field,
                    missing_required_fields=missing,
                    draft_changes=draft_changes or None,
                )

            if raw_message.strip().lower() in _EDIT_TERMS and not saved_fields and not removed_fields:
                session["state"] = OnboardingState.COLLECTING.value
                session["current_question_field"] = None
                return PatientOnboardingChatResponse(
                    reply="Tell me what you'd like to change in your onboarding answers.",
                    state=OnboardingState.COLLECTING.value,
                    current_question_field=None,
                    missing_required_fields=missing,
                    draft_changes=draft_changes or None,
                )

            if saved_fields or removed_fields:
                if missing:
                    next_field = missing[0]
                    session["state"] = OnboardingState.COLLECTING.value
                    session["current_question_field"] = next_field
                    return PatientOnboardingChatResponse(
                        reply=self._build_collecting_reply(
                            saved_fields=saved_fields,
                            removed_fields=removed_fields,
                            next_field=next_field,
                        ),
                        state=OnboardingState.COLLECTING.value,
                        current_question_field=next_field,
                        missing_required_fields=missing,
                        draft_changes=draft_changes or None,
                    )

                session["state"] = OnboardingState.REVIEWING.value
                session["current_question_field"] = None
                return PatientOnboardingChatResponse(
                    reply=self._build_review_summary(existing_answers, draft_changes),
                    state=OnboardingState.REVIEWING.value,
                    current_question_field=None,
                    missing_required_fields=[],
                    draft_changes=draft_changes or None,
                )

            return PatientOnboardingChatResponse(
                reply=self._build_review_summary(existing_answers, draft_changes),
                state=OnboardingState.REVIEWING.value,
                current_question_field=None,
                missing_required_fields=[],
                draft_changes=draft_changes or None,
            )

        if errors:
            next_field = errors[0][0]
            session["state"] = OnboardingState.COLLECTING.value
            session["current_question_field"] = next_field
            return PatientOnboardingChatResponse(
                reply=self._build_error_question_reply(errors, next_field),
                state=OnboardingState.COLLECTING.value,
                current_question_field=next_field,
                missing_required_fields=missing,
                draft_changes=draft_changes or None,
            )

        if not missing:
            session["state"] = OnboardingState.REVIEWING.value
            session["current_question_field"] = None
            return PatientOnboardingChatResponse(
                reply=self._build_review_summary(existing_answers, draft_changes),
                state=OnboardingState.REVIEWING.value,
                current_question_field=None,
                missing_required_fields=[],
                draft_changes=draft_changes or None,
            )

        next_field = missing[0]
        session["state"] = OnboardingState.COLLECTING.value
        session["current_question_field"] = next_field
        if not saved_fields and not removed_fields and not parsed.actions:
            reply = (
                "I couldn't map that to one of your onboarding fields yet.\n\n"
                + self._question_for_field(next_field)
            )
        else:
            reply = self._build_collecting_reply(
                saved_fields=saved_fields,
                removed_fields=removed_fields,
                next_field=next_field,
            )
        return PatientOnboardingChatResponse(
            reply=reply,
            state=OnboardingState.COLLECTING.value,
            current_question_field=next_field,
            missing_required_fields=missing,
            draft_changes=draft_changes or None,
        )

    def _apply_actions_to_draft(
        self,
        draft_changes: Dict[str, Any],
        actions: List[LLMAction],
    ) -> Tuple[Dict[str, Any], str, List[str], List[str], List[Tuple[str, str]]]:
        signal = "continue"
        saved_fields: List[str] = []
        removed_fields: List[str] = []
        errors: List[Tuple[str, str]] = []

        for action in actions:
            if action.action == "set":
                field = action.field
                if not field or field not in _VALID_FIELDS or action.value is None:
                    continue
                try:
                    draft_changes[field] = self._normalize_value(field, action.value)
                    saved_fields.append(field)
                except ValueError as exc:
                    errors.append((field, str(exc)))
            elif action.action == "remove":
                field = action.field
                if field and field in draft_changes:
                    draft_changes.pop(field, None)
                    removed_fields.append(field)
            elif action.action == "confirm_all":
                signal = "review"
            elif action.action == "cancel_all":
                draft_changes.clear()
                signal = "cancel"

        return draft_changes, signal, saved_fields, removed_fields, errors

    async def _extract_intent(
        self,
        *,
        messages: List[Dict[str, str]],
        current_field: Optional[str],
        missing_required_fields: List[str],
    ) -> LLMResponse:
        llm_messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    current_field=current_field,
                    missing_required_fields=missing_required_fields,
                ),
            },
            *messages,
        ]
        try:
            response = await self.openai_client.chat.completions.create(
                model=_LLM_MODEL,
                messages=llm_messages,
                temperature=0.0,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            raw = json.loads(content)
            actions: List[LLMAction] = []
            for item in raw.get("actions", []):
                try:
                    actions.append(LLMAction(**item))
                except Exception:
                    logger.debug("Skipping invalid onboarding action: %s", item)
            return LLMResponse(actions=actions, reply=raw.get("reply", ""))
        except json.JSONDecodeError:
            logger.warning("Onboarding agent returned invalid JSON.")
            return LLMResponse()
        except Exception:
            logger.exception("OpenAI call failed during patient onboarding chat.")
            return LLMResponse()

    @staticmethod
    def _normalize_value(field: str, raw_value: Any) -> Any:
        value = PatientOnboardingAgentService._coerce_value(field, raw_value)
        if isinstance(value, _date):
            return value.isoformat()
        if isinstance(value, _time):
            return value.strftime("%H:%M")
        return value

    @staticmethod
    def _coerce_value(field: str, raw_value: Any) -> Any:
        if field in (
            OnboardingField.HEIGHT.value,
            OnboardingField.WEIGHT.value,
            OnboardingField.WAIST.value,
        ):
            try:
                value = float(raw_value)
            except (ValueError, TypeError):
                raise ValueError("Please provide a valid number.")
            limits = {
                OnboardingField.HEIGHT.value: (30, 300),
                OnboardingField.WEIGHT.value: (1, 500),
                OnboardingField.WAIST.value: (20, 300),
            }
            low, high = limits[field]
            if not (low <= value <= high):
                raise ValueError(f"Value should be between {low} and {high}.")
            return value

        if field in (
            OnboardingField.MEALS_PER_DAY.value,
            OnboardingField.SNACKS_COUNT.value,
            OnboardingField.YEARS_OF_SMOKING.value,
            OnboardingField.CIGARETTES_PER_DAY.value,
            OnboardingField.QUIT_YEARS_AGO.value,
            OnboardingField.YEARS_WITH_DIABETES.value,
            OnboardingField.PREGNANCY_WEEKS.value,
        ):
            try:
                if isinstance(raw_value, bool):
                    raise ValueError
                value = int(raw_value)
            except (ValueError, TypeError):
                raise ValueError("Please provide a whole number.")
            if value < 0:
                raise ValueError("Value cannot be negative.")
            return value

        if field == OnboardingField.DOB.value:
            if isinstance(raw_value, _date):
                return raw_value
            if not isinstance(raw_value, str):
                raise ValueError("Date of birth must be in YYYY-MM-DD format.")
            raw = raw_value.strip()
            if re.fullmatch(r"\d{4}", raw):
                raw = f"{raw}-01-01"
            try:
                return _date.fromisoformat(raw)
            except ValueError:
                raise ValueError("Date of birth must be in YYYY-MM-DD format.")

        if field in (
            OnboardingField.WAKE_UP_TIME.value,
            OnboardingField.BED_TIME.value,
        ):
            if isinstance(raw_value, _time):
                return raw_value
            if not isinstance(raw_value, str):
                raise ValueError("Please use HH:MM in 24-hour time.")
            try:
                return _time.fromisoformat(raw_value.strip())
            except ValueError:
                raise ValueError("Please use HH:MM in 24-hour time.")

        if field in (
            OnboardingField.GENDER.value,
            OnboardingField.ACTIVITY_LEVEL.value,
            OnboardingField.SLEEP_QUALITY.value,
        ):
            if not isinstance(raw_value, str):
                raise ValueError("Please provide a text answer.")
            normalized = raw_value.strip().lower().replace(" ", "_")
            if field == OnboardingField.GENDER.value:
                normalized = normalized.replace("_", " ")
                if normalized not in _VALID_GENDERS:
                    raise ValueError("Gender must be male, female, or other.")
                return normalized
            if field == OnboardingField.ACTIVITY_LEVEL.value:
                if normalized not in _VALID_ACTIVITY_LEVELS:
                    raise ValueError(
                        "Activity level must be sedentary, light, moderate, active, or very active."
                    )
                return normalized
            if normalized not in _VALID_SLEEP_QUALITIES:
                raise ValueError("Sleep quality must be good, average, or poor.")
            return normalized

        if field in (
            OnboardingField.CONSUME_ALCOHOL.value,
            OnboardingField.SMOKE_STATUS.value,
            OnboardingField.WAKE_UP_FRESH.value,
            OnboardingField.DROWSY_DAY.value,
            OnboardingField.IS_PREGNANT.value,
            OnboardingField.HAS_MEDICATION.value,
        ):
            if isinstance(raw_value, bool):
                return raw_value
            if isinstance(raw_value, str):
                normalized = raw_value.strip().lower()
                if normalized in _BOOL_TRUE:
                    return True
                if normalized in _BOOL_FALSE:
                    return False
            raise ValueError("Please answer with yes or no.")

        if field == OnboardingField.EMAIL.value:
            if not isinstance(raw_value, str):
                raise ValueError("Please provide a valid email address.")
            email = raw_value.strip().lower()
            if not _EMAIL_RE.match(email):
                raise ValueError("Please provide a valid email address.")
            return email

        if field in (
            OnboardingField.FOOD_ALLERGIES.value,
            OnboardingField.DRUG_ALLERGIES.value,
            OnboardingField.MEDICAL_CONDITIONS.value,
            OnboardingField.TYPE_OF_ALCOHOL.value,
        ):
            if isinstance(raw_value, list):
                items = [str(item).strip() for item in raw_value if str(item).strip()]
            elif isinstance(raw_value, str):
                items = [part.strip() for part in raw_value.split(",") if part.strip()]
            else:
                raise ValueError("Please provide one or more values.")
            if not items:
                raise ValueError("Please provide at least one value.")
            return items

        if not isinstance(raw_value, str):
            raw_value = str(raw_value)
        return raw_value.strip()

    def _load_existing_field_values(
        self,
        patient: PatientModel,
    ) -> Dict[str, Any]:
        values: Dict[str, Any] = {
            field.value: getattr(patient, field.value, None)
            for field in (
                OnboardingField.FIRST_NAME,
                OnboardingField.LAST_NAME,
                OnboardingField.EMAIL,
                OnboardingField.DOB,
                OnboardingField.GENDER,
                OnboardingField.HEIGHT,
                OnboardingField.WEIGHT,
                OnboardingField.WAIST,
                OnboardingField.LOCALE,
            )
        }

        if patient.daily_activity:
            values[OnboardingField.ACTIVITY_LEVEL.value] = (
                patient.daily_activity.activity_level
            )
        if patient.alcohol_consumption:
            values[OnboardingField.CONSUME_ALCOHOL.value] = (
                patient.alcohol_consumption.consume_alcohol
            )
            values[OnboardingField.ALCOHOL_FREQUENCY.value] = (
                patient.alcohol_consumption.frequency
            )
            values[OnboardingField.ALCOHOL_QUANTITY.value] = (
                patient.alcohol_consumption.quantity
            )
            values[OnboardingField.TYPE_OF_ALCOHOL.value] = (
                patient.alcohol_consumption.type_of_alcohol
            )
        if patient.smoking_habit:
            values[OnboardingField.SMOKE_STATUS.value] = (
                patient.smoking_habit.smoke_status
            )
            values[OnboardingField.YEARS_OF_SMOKING.value] = (
                patient.smoking_habit.years_of_smoking
            )
            values[OnboardingField.CIGARETTES_PER_DAY.value] = (
                patient.smoking_habit.cigarettes_per_day
            )
            values[OnboardingField.QUIT_YEARS_AGO.value] = (
                patient.smoking_habit.quit_years_ago
            )
        if patient.sleep_habit:
            values[OnboardingField.SLEEP_QUALITY.value] = (
                patient.sleep_habit.sleep_quality
            )
            values[OnboardingField.WAKE_UP_FRESH.value] = (
                patient.sleep_habit.wake_up_fresh
            )
            values[OnboardingField.DROWSY_DAY.value] = (
                patient.sleep_habit.drowsy_day
            )
            values[OnboardingField.AVERAGE_SLEEP_DURATION.value] = (
                patient.sleep_habit.average_sleep_duration
            )
            if patient.sleep_habit.wake_up_time:
                values[OnboardingField.WAKE_UP_TIME.value] = (
                    patient.sleep_habit.wake_up_time.strftime("%H:%M")
                )
            if patient.sleep_habit.bed_time:
                values[OnboardingField.BED_TIME.value] = (
                    patient.sleep_habit.bed_time.strftime("%H:%M")
                )
        if patient.eating_habit:
            values[OnboardingField.MEALS_PER_DAY.value] = (
                patient.eating_habit.meals_per_day
            )
            values[OnboardingField.SNACKS_COUNT.value] = (
                patient.eating_habit.snacks_count
            )
        if patient.food_allergies:
            values[OnboardingField.FOOD_ALLERGIES.value] = [
                allergy.allergy_name for allergy in patient.food_allergies
            ]
        if patient.diabetic_history:
            values[OnboardingField.TYPE_OF_DIABETES.value] = (
                patient.diabetic_history.type_of_diabetes
            )
            values[OnboardingField.YEARS_WITH_DIABETES.value] = (
                patient.diabetic_history.years_with_diabetes
            )
            values[OnboardingField.IS_PREGNANT.value] = (
                patient.diabetic_history.is_pregnant
            )
            values[OnboardingField.PREGNANCY_WEEKS.value] = (
                patient.diabetic_history.pregnancy_weeks
            )
    
        if patient.drug_allergies:
            values[OnboardingField.DRUG_ALLERGIES.value] = [
                allergy.allergy_name for allergy in patient.drug_allergies
            ]
        if patient.medical_histories:
            values[OnboardingField.MEDICAL_CONDITIONS.value] = [
                item.condition for item in patient.medical_histories
            ]

        if isinstance(values.get(OnboardingField.DOB.value), _date):
            values[OnboardingField.DOB.value] = values[
                OnboardingField.DOB.value
            ].isoformat()
        return values

    async def _load_existing_answers(self, patient_id: str) -> Dict[str, Any]:
        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id,
            detailed=True,
        )
        return self._load_existing_field_values(patient)

    @staticmethod
    def _merge_answers(
        existing_answers: Dict[str, Any],
        draft_changes: Dict[str, Any],
    ) -> Dict[str, Any]:
        merged = dict(existing_answers)
        merged.update(draft_changes)
        return merged

    @staticmethod
    def _field_present(value: Any) -> bool:
        if isinstance(value, bool):
            return True
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return len(value) > 0
        return True

    def _compute_missing_required_fields(
        self,
        existing_answers: Dict[str, Any],
        draft_changes: Dict[str, Any],
    ) -> List[str]:
        merged = self._merge_answers(existing_answers, draft_changes)
        return [
            field for field in QUESTION_ORDER if not self._field_present(merged.get(field))
        ]

    def _question_for_field(self, field: Optional[str]) -> str:
        if not field:
            return "Tell me the next detail you'd like to add."
        return _QUESTION_PROMPTS.get(
            field,
            f"Please share your {OnboardingField.human_labels().get(field, field)}.",
        )

    def _build_collecting_reply(
        self,
        *,
        saved_fields: List[str],
        removed_fields: List[str],
        next_field: str,
    ) -> str:
        parts: List[str] = []
        labels = OnboardingField.human_labels()
        if saved_fields:
            parts.append(
                "Saved: " + ", ".join(labels.get(field, field) for field in saved_fields) + "."
            )
        if removed_fields:
            parts.append(
                "Removed: "
                + ", ".join(labels.get(field, field) for field in removed_fields)
                + "."
            )
        parts.append(self._question_for_field(next_field))
        return "\n\n".join(parts)

    def _build_error_question_reply(
        self,
        errors: List[Tuple[str, str]],
        next_field: str,
    ) -> str:
        labels = OnboardingField.human_labels()
        lines = [
            f"{labels.get(field, field)}: {message}" for field, message in errors
        ]
        return (
            "I need a quick correction before I continue:\n"
            + "\n".join(f"• {line}" for line in lines)
            + "\n\n"
            + self._question_for_field(next_field)
        )

    def _build_review_summary(
        self,
        existing_answers: Dict[str, Any],
        draft_changes: Dict[str, Any],
    ) -> str:
        merged = self._merge_answers(existing_answers, draft_changes)
        display_order = [
            field for field in QUESTION_ORDER if self._field_present(merged.get(field))
        ]
        for field in draft_changes:
            if field not in display_order:
                display_order.append(field)

        labels = OnboardingField.human_labels()
        lines = [
            f"• {labels.get(field, field)}: {self._display_value(merged.get(field))}"
            for field in display_order
        ]
        return (
            "I have the details I need for onboarding. Please review:\n"
            + "\n".join(lines)
            + "\n\nReply 'confirm' to save this, or tell me what to change."
        )

    @staticmethod
    def _display_value(value: Any) -> str:
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)

    def _parse_review_shortcuts(
        self,
        session: Dict[str, Any],
        raw_message: str,
    ) -> Optional[LLMResponse]:
        if session.get("state") != OnboardingState.REVIEWING.value:
            return None
        text = raw_message.strip().lower()
        if text in _CONFIRM_TERMS:
            return LLMResponse(actions=[LLMAction(action="confirm_all")])
        if text in {"cancel", "restart", "start over"}:
            return LLMResponse(actions=[LLMAction(action="cancel_all")])
        return None

    def _reset_session(self, patient_id: str) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "patient_id": patient_id,
            "status": "active",
            "state": OnboardingState.COLLECTING.value,
            "current_question_field": None,
            "draft_changes": {},
            "messages": [],
            "created_at": now,
            "updated_at": now,
        }

    async def _ensure_indexes_once(self) -> None:
        if self._indexes_ensured:
            return
        await self.ensure_indexes()
        self._indexes_ensured = True

    async def _get_or_create_session(self, patient_id: str) -> Dict[str, Any]:
        doc = await self.conversation_collection.find_one(
            {"patient_id": patient_id, "status": "active"}
        )
        if doc:
            return doc

        new_doc = self._reset_session(patient_id)
        try:
            await self.conversation_collection.insert_one(new_doc)
        except DuplicateKeyError:
            doc = await self.conversation_collection.find_one(
                {"patient_id": patient_id, "status": "active"}
            )
            if doc:
                return doc
        return new_doc

    async def _save_session(self, session: Dict[str, Any]) -> None:
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self.conversation_collection.replace_one(
            {"patient_id": session["patient_id"], "status": "active"},
            session,
            upsert=True,
        )

    @with_postgres_session
    async def _apply_draft_batch(
        self,
        patient_id: str,
        draft_changes: Dict[str, Any],
        *,
        postgres_session: AsyncSession,
    ) -> None:
        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id,
            detailed=True,
            postgres_session=postgres_session,
        )

        for field, raw_value in draft_changes.items():
            value = self._coerce_value(field, raw_value)
            section = FIELD_TO_SECTION.get(field, "basic")
            if section == "basic":
                self._mutate_basic_field(patient, field, value)
            elif section == "lifestyle":
                self._mutate_lifestyle_field(patient, patient_id, field, value)
            elif section == "medical_history":
                self._mutate_medical_history_field(patient, patient_id, field, value)

        self._refresh_profile_completion(patient)
        postgres_session.add(patient)
        await postgres_session.commit()

        try:
            await self.patient_profile_service.chat_notification_service.notify_participants(
                message_key="chat_list_updated",
                user_id=patient_id,
            )
        except Exception:
            logger.warning(
                "Failed to notify participants after onboarding apply for %s",
                patient_id,
                exc_info=True,
            )

        try:
            await postgres_session.refresh(patient)
            detailed = await self.patient_profile_service.fetch_patient_profile(
                patient_id,
                detailed=True,
                postgres_session=postgres_session,
            )
            profile_data = CorePatientProfile.from_orm(detailed).model_dump(
                mode="json"
            )
            await enqueue_generate_profile_vector_async(patient_id, profile_data)
        except Exception:
            logger.warning(
                "Failed to enqueue profile vector sync after onboarding apply for %s",
                patient_id,
                exc_info=True,
            )

    @staticmethod
    def _mutate_basic_field(
        patient: PatientModel,
        field: str,
        value: Any,
    ) -> None:
        if field not in {"created_at", "updated_at", "phone_number"}:
            setattr(patient, field, value)

    @staticmethod
    def _mutate_lifestyle_field(
        patient: PatientModel,
        patient_id: str,
        field: str,
        value: Any,
    ) -> None:
        if field == OnboardingField.ACTIVITY_LEVEL.value:
            if patient.daily_activity:
                patient.daily_activity.activity_level = value
            else:
                patient.daily_activity = PatientDailyActivityModel(
                    patient_id=patient_id,
                    activity_level=value,
                )
        elif field in {
            OnboardingField.CONSUME_ALCOHOL.value,
            OnboardingField.ALCOHOL_FREQUENCY.value,
            OnboardingField.ALCOHOL_QUANTITY.value,
            OnboardingField.TYPE_OF_ALCOHOL.value,
        }:
            alcohol = patient.alcohol_consumption or PatientAlcoholConsumptionModel(
                patient_id=patient_id,
                consume_alcohol=False,
            )
            if field == OnboardingField.CONSUME_ALCOHOL.value:
                alcohol.consume_alcohol = value
            elif field == OnboardingField.ALCOHOL_FREQUENCY.value:
                alcohol.frequency = value
            elif field == OnboardingField.ALCOHOL_QUANTITY.value:
                alcohol.quantity = value
            else:
                alcohol.type_of_alcohol = value
            patient.alcohol_consumption = alcohol
        elif field in {
            OnboardingField.SMOKE_STATUS.value,
            OnboardingField.YEARS_OF_SMOKING.value,
            OnboardingField.CIGARETTES_PER_DAY.value,
            OnboardingField.QUIT_YEARS_AGO.value,
        }:
            smoking = patient.smoking_habit or PatientSmokingHabitModel(
                patient_id=patient_id,
                smoke_status=False,
            )
            if field == OnboardingField.SMOKE_STATUS.value:
                smoking.smoke_status = value
            elif field == OnboardingField.YEARS_OF_SMOKING.value:
                smoking.years_of_smoking = value
            elif field == OnboardingField.CIGARETTES_PER_DAY.value:
                smoking.cigarettes_per_day = value
            else:
                smoking.quit_years_ago = value
            patient.smoking_habit = smoking
        elif field in {
            OnboardingField.SLEEP_QUALITY.value,
            OnboardingField.WAKE_UP_FRESH.value,
            OnboardingField.DROWSY_DAY.value,
            OnboardingField.AVERAGE_SLEEP_DURATION.value,
            OnboardingField.WAKE_UP_TIME.value,
            OnboardingField.BED_TIME.value,
        }:
            sleep = patient.sleep_habit or PatientSleepHabitModel(
                patient_id=patient_id,
                sleep_quality="average",
            )
            if field == OnboardingField.SLEEP_QUALITY.value:
                sleep.sleep_quality = value
            elif field == OnboardingField.WAKE_UP_FRESH.value:
                sleep.wake_up_fresh = value
            elif field == OnboardingField.DROWSY_DAY.value:
                sleep.drowsy_day = value
            elif field == OnboardingField.AVERAGE_SLEEP_DURATION.value:
                sleep.average_sleep_duration = value
            elif field == OnboardingField.WAKE_UP_TIME.value:
                sleep.wake_up_time = value
            else:
                sleep.bed_time = value
            patient.sleep_habit = sleep
        elif field in {
            OnboardingField.MEALS_PER_DAY.value,
            OnboardingField.SNACKS_COUNT.value,
        }:
            eating = patient.eating_habit or PatientEatingHabitModel(
                patient_id=patient_id
            )
            if field == OnboardingField.MEALS_PER_DAY.value:
                eating.meals_per_day = value
            else:
                eating.snacks_count = value
            patient.eating_habit = eating
        elif field == OnboardingField.FOOD_ALLERGIES.value:
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
        if field in {
            OnboardingField.TYPE_OF_DIABETES.value,
            OnboardingField.YEARS_WITH_DIABETES.value,
            OnboardingField.IS_PREGNANT.value,
            OnboardingField.PREGNANCY_WEEKS.value,
        }:
            history = patient.diabetic_history or PatientDiabeticHistoryModel(
                patient_id=patient_id
            )
            if field == OnboardingField.TYPE_OF_DIABETES.value:
                history.type_of_diabetes = value
            elif field == OnboardingField.YEARS_WITH_DIABETES.value:
                history.years_with_diabetes = value
            elif field == OnboardingField.IS_PREGNANT.value:
                history.is_pregnant = value
            else:
                history.pregnancy_weeks = value
            patient.diabetic_history = history
        elif field == OnboardingField.DRUG_ALLERGIES.value:
            patient.drug_allergies = [
                PatientDrugAllergyModel(patient_id=patient_id, allergy_name=name)
                for name in value
            ]
        elif field == OnboardingField.MEDICAL_CONDITIONS.value:
            patient.medical_histories = [
                PatientMedicalHistoryModel(
                    patient_id=patient_id,
                    condition=name,
                    duration_years=0,
                )
                for name in value
            ]

    def _refresh_profile_completion(self, patient: PatientModel) -> None:
        profile_completion = dict(patient.profile_completion or {})
        changed = False
        current_values = self._load_existing_field_values(patient)

        for section, required_fields in _SECTION_REQUIRED_FIELDS.items():
            entry = dict(
                profile_completion.get(
                    section,
                    {"is_complete": False, "is_mandatory": True},
                )
            )
            is_complete = all(
                self._field_present(current_values.get(field))
                for field in required_fields
            )
            if entry.get("is_complete") != is_complete:
                entry["is_complete"] = is_complete
                profile_completion[section] = entry
                changed = True

        if changed:
            patient.profile_completion = profile_completion
            flag_modified(patient, "profile_completion")
