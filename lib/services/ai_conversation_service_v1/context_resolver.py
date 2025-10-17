import json
from typing import Any, Dict, List, Optional, Set
from lib.core.cache_store import CacheStore
from lib.schemas.patient import CorePatientProfile as CorePatientProfileSchema
from lib.services.patient_profile_service import PatientProfileService
from qdrant_client.models import ScoredPoint


class AIConversationContextResolver:
    def __init__(
        self,
        patient_profile_store: CacheStore,
        patient_profile_service: PatientProfileService,
    ):
        self.patient_profile_store = patient_profile_store
        self.patient_profile_service = patient_profile_service

    async def resolve_context(
        self,
        qdrant_results: list[ScoredPoint],
    ) -> Dict[str, Any]:
        patient_ids: Set[str] = set()
        profiles_found: Set[str] = set()

        # Phase 1: Collect patient IDs
        for result in qdrant_results:
            payload = result.payload or {}
            patient_id = payload.get("patient_id")
            if not patient_id:
                continue
            patient_ids.add(patient_id)
            if payload.get("data_type") == "profile":
                profiles_found.add(patient_id)

        # Phase 2: Find missing profile IDs
        missing_profiles = list(patient_ids - profiles_found)
        resolved_profiles: Dict[str, Any] = {}

        if missing_profiles:
            resolved_profiles = await self._get_profiles_from_cache_or_db(
                missing_profiles
            )

        return {
            "patient_ids": list(patient_ids),
            "profiles_found": list(profiles_found),
            "profiles_added": resolved_profiles,
        }

    async def _get_profiles_from_cache_or_db(
        self, patient_ids: List[str]
    ) -> Dict[str, Any]:
        cached_profiles = {}
        missing_from_cache = []

        # Try to get from Redis first
        for pid in patient_ids:
            cache_key = f"patient_profile:{pid}"
            cached = self.patient_profile_store.get_key(cache_key)
            if cached:
                cached_profiles[pid] = json.loads(cached)
            else:
                missing_from_cache.append(pid)

        # Fetch missing ones from DB in a single batch
        if missing_from_cache:
            db_profiles = (
                await self.patient_profile_service.fetch_patient_profiles(
                    patient_ids=missing_from_cache,
                    detailed=True,
                )  # type: ignore
            )

            # Convert ORM → schema + cache them
            for pid, profile_obj in db_profiles.items():
                profile_data = CorePatientProfileSchema.from_orm(
                    profile_obj
                ).model_dump(mode="json")
                cached_profiles[pid] = profile_data
                self.patient_profile_store.set_key(
                    pid, json.dumps(profile_data), expire=3600 * 12
                )

        return cached_profiles
