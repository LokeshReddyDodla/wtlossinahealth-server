"""Service responsible for persisting weightloss intake forms (exercise, fitness, willingness)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorCollection

from lib.schemas.weightloss_agent.intake import (
    ExercisePreferencesCreate,
    ExercisePreferencesRecord,
    FitnessScreenCreate,
    FitnessScreenRecord,
    WillingnessCommitmentCreate,
    WillingnessCommitmentRecord,
)
from lib.services.weightloss_agent.analytics_service import AnalyticsService


class IntakeService:
    def __init__(
        self,
        exercise_preferences_collection: AsyncIOMotorCollection,
        fitness_screen_collection: AsyncIOMotorCollection,
        willingness_commitment_collection: AsyncIOMotorCollection,
        analytics_service: AnalyticsService,
    ) -> None:
        self.exercise_preferences_collection = (
            exercise_preferences_collection
        )
        self.fitness_screen_collection = fitness_screen_collection
        self.willingness_commitment_collection = (
            willingness_commitment_collection
        )
        self.analytics_service = analytics_service

    async def save_exercise_preferences(
        self, payload: ExercisePreferencesCreate
    ) -> ExercisePreferencesRecord:
        preference_id = uuid4()
        now = datetime.now(timezone.utc)
        payload_dict = self._serialize_payload(payload)
        doc = {
            "preference_id": str(preference_id),
            "patient_id": str(payload.patient_id),
            "payload": payload_dict,
            "created_at": now,
            "updated_at": now,
            "provenance": {"component": "exercise_preferences"},
        }
        await self.exercise_preferences_collection.insert_one(doc)

        await self._emit_intake_events(
            patient_id=str(payload.patient_id),
            form_name="exercise_preferences",
            payload=payload.model_dump(),
        )

        payload_data = payload.model_dump(exclude={"patient_id"})

        return ExercisePreferencesRecord(
            preference_id=preference_id,
            patient_id=payload.patient_id,
            created_at=now,
            updated_at=now,
            version="2025.03",
            provenance=doc["provenance"],
            **payload_data,
        )

    async def save_fitness_screen(
        self, payload: FitnessScreenCreate
    ) -> FitnessScreenRecord:
        screen_id = uuid4()
        now = datetime.now(timezone.utc)
        payload_dict = self._serialize_payload(payload)
        doc = {
            "screen_id": str(screen_id),
            "patient_id": str(payload.patient_id),
            "payload": payload_dict,
            "screened_at": now,
            "provenance": {"component": "fitness_screen"},
        }
        await self.fitness_screen_collection.insert_one(doc)
        await self._emit_intake_events(
            patient_id=str(payload.patient_id),
            form_name="fitness_screen",
            payload=payload.model_dump(),
        )

        payload_data = payload.model_dump(exclude={"patient_id"})

        return FitnessScreenRecord(
            screen_id=screen_id,
            patient_id=payload.patient_id,
            screened_at=now,
            version="2025.03",
            provenance=doc["provenance"],
            **payload_data,
        )

    async def save_willingness_commitment(
        self, payload: WillingnessCommitmentCreate
    ) -> WillingnessCommitmentRecord:
        willingness_id = uuid4()
        now = datetime.now(timezone.utc)
        payload_dict = self._serialize_payload(payload)
        doc = {
            "willingness_id": str(willingness_id),
            "patient_id": str(payload.patient_id),
            "payload": payload_dict,
            "captured_at": now,
            "provenance": {"component": "willingness_commitment"},
        }
        await self.willingness_commitment_collection.insert_one(doc)
        await self._emit_intake_events(
            patient_id=str(payload.patient_id),
            form_name="willingness_commitment",
            payload=payload.model_dump(),
        )

        payload_data = payload.model_dump(exclude={"patient_id"})

        return WillingnessCommitmentRecord(
            willingness_id=willingness_id,
            patient_id=payload.patient_id,
            captured_at=now,
            version="2025.03",
            provenance=doc["provenance"],
            **payload_data,
        )

    async def get_latest_exercise_preferences(
        self, patient_id: UUID
    ) -> Optional[Dict[str, Any]]:
        doc = await self.exercise_preferences_collection.find_one(
            {"patient_id": str(patient_id)},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        return self._expand_payload(doc)

    async def get_latest_fitness_screen(
        self, patient_id: UUID
    ) -> Optional[Dict[str, Any]]:
        doc = await self.fitness_screen_collection.find_one(
            {"patient_id": str(patient_id)}, sort=[("screened_at", -1)]
        )
        return self._expand_payload(doc)

    async def get_latest_willingness(
        self, patient_id: UUID
    ) -> Optional[Dict[str, Any]]:
        doc = await self.willingness_commitment_collection.find_one(
            {"patient_id": str(patient_id)}, sort=[("captured_at", -1)]
        )
        return self._expand_payload(doc)

    async def _emit_intake_events(
        self, patient_id: str, form_name: str, payload: Dict[str, Any]
    ) -> None:
        await self.analytics_service.emit_event(
            event_type="intake_started",
            user_id=patient_id,
            payload={"form": form_name},
        )
        await self.analytics_service.emit_event(
            event_type="intake_completed",
            user_id=patient_id,
            payload={"form": form_name},
        )

        missing_fields = [
            key for key, value in payload.items() if value in (None, [], "")
        ]
        for field_name in missing_fields:
            await self.analytics_service.emit_event(
                event_type="field_deferred",
                user_id=patient_id,
                payload={"form": form_name, "field": field_name},
                severity="warning",
            )

    def _expand_payload(
        self, doc: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        if not doc:
            return None
        payload = doc.get("payload", {}).copy()
        payload["provenance"] = doc.get("provenance", {})
        payload["patient_id"] = doc.get("patient_id")
        for key in (
            "preference_id",
            "created_at",
            "updated_at",
            "screen_id",
            "screened_at",
            "willingness_id",
            "captured_at",
        ):
            if key in doc:
                payload[key] = doc[key]
        return payload

    def _serialize_payload(self, payload_model: Any) -> Dict[str, Any]:
        """
        Ensure nested UUIDs and other non-JSON types are converted into strings before Mongo insert.
        """
        return json.loads(
            json.dumps(payload_model.model_dump(), default=str)
        )
