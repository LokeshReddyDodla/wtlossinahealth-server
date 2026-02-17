"""Profile Update micro-agent service.

Manages a short multi-turn conversation to update a single profile field,
backed by Mongo for conversation state and Postgres (via PatientProfileService)
for the actual write.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorCollection
from openai import AsyncOpenAI

from lib.core.postgres_store import PostgresStore
from lib.schemas.patient import PatientUpdate
from lib.schemas.profile_update_agent import (
    ConversationState,
    ProfileUpdateChatResponse,
    UpdatableField,
)
from lib.services.patient_profile_service import PatientProfileService
from lib.services.profile_update_agent.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# OpenAI model to use — centralised so it's easy to change later.
_LLM_MODEL = "gpt-4o-mini"


class ProfileUpdateAgentService:
    """Lightweight conversational agent for profile updates.

    Design decisions:
    * One Mongo document per conversation, keyed by ``conversation_id``.
    * FSM states live in ``ConversationState``; transitions happen in
      ``_advance_state``.
    * The LLM is only used for *intent extraction* — all mutation logic is
      deterministic so it can be tested / audited without an LLM in the loop.
    * ``PatientProfileService.update_basic_patient_profile`` is reused for the
      actual Postgres write, preserving existing validation, events, and vector
      store sync.
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
                # Perform the actual update
                target_field = conv["target_field"]
                target_value = conv["target_value"]

                coerced_value = self._coerce_value(target_field, target_value)
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

    # ── Postgres write (delegates to existing service) ──────────────────────
    async def _apply_update(
        self, patient_id: str, field: str, value: Any
    ) -> None:
        """Build a ``PatientUpdate`` with a single field and delegate to
        ``PatientProfileService``."""

        # PatientUpdate inherits PatientBase which requires phone_number.
        # We pass a dummy value — update_basic_patient_profile skips
        # phone_number anyway (it's in the exclude list).
        update_data = PatientUpdate.model_construct(
            **{field: value, "phone_number": ""}
        )

        # model_construct bypasses validation so model_fields_set is empty;
        # we need to set it manually so model_dump(exclude_unset=True) works.
        update_data.model_fields_set.add(field)

        await self.patient_profile_service.update_basic_patient_profile(
            patient_id=patient_id,
            patient_data=update_data,
        )
        logger.info(
            "Profile field '%s' updated for patient %s", field, patient_id
        )

    # ── Value coercion ──────────────────────────────────────────────────────
    @staticmethod
    def _coerce_value(field: str, raw_value: str) -> Any:
        """Convert the string value from the LLM into the Python type
        expected by the Patient model."""

        if field in ("height", "weight", "waist"):
            try:
                return float(raw_value)
            except (ValueError, TypeError):
                return raw_value
        if field == "dob":
            # Accept YYYY-MM-DD from the LLM (the prompt asks for this format)
            from datetime import date as _date

            try:
                return _date.fromisoformat(raw_value)
            except (ValueError, TypeError):
                return raw_value
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
