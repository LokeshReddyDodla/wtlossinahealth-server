"""Mongo store for `patient_panel_signal` — the materialized read model."""

from __future__ import annotations

from typing import Any

from lib.schemas.patient_panel_signal import PatientPanelSignal

_SORTABLE = {
    "priority", "name", "tir_pct", "avg_glucose", "cv_pct", "gmi",
    "below_70_pct", "above_180_pct", "a1c", "adherence_pct", "avg_steps",
    "avg_sleep_hours", "last_glucose_at", "last_active_at", "computed_at",
}


class PatientPanelStore:
    def __init__(self, collection):
        self._col = collection

    async def ensure_indexes(self) -> None:
        await self._col.create_index("patient_id", name="panel_patient_idx", unique=True)
        await self._col.create_index(
            [("facility_id", 1), ("care_provider_ids", 1), ("priority", 1)],
            name="panel_scope_priority_idx",
        )
        await self._col.create_index(
            [("facility_id", 1), ("assessment", 1)], name="panel_scope_assessment_idx"
        )
        await self._col.create_index(
            [("facility_id", 1), ("modality", 1)], name="panel_scope_modality_idx"
        )
        await self._col.create_index(
            [("facility_id", 1), ("priority", 1), ("patient_id", 1)],
            name="panel_facility_priority_idx",
        )
        await self._col.create_index(
            [("care_provider_ids", 1), ("priority", 1), ("patient_id", 1)],
            name="panel_cp_priority_idx",
        )

    async def get(self, patient_id: str) -> dict[str, Any] | None:
        return await self._col.find_one({"patient_id": patient_id}, {"_id": 0})

    async def delete(self, patient_id: str) -> bool:
        result = await self._col.delete_one({"patient_id": patient_id})
        return result.deleted_count > 0

    async def upsert(self, signal: PatientPanelSignal) -> None:
        doc = signal.model_dump(mode="json")
        doc.pop("reviewed_at", None)  # owned by mark_reviewed; never overwrite a concurrent review
        await self._col.update_one(
            {"patient_id": signal.patient_id}, {"$set": doc}, upsert=True
        )

    async def mark_reviewed(
        self, patient_id: str, at: str, state_since: str | None = None
    ) -> str:
        flt: dict[str, Any] = {"patient_id": patient_id}
        if state_since is not None:
            flt["state_since"] = state_since
        result = await self._col.update_one(
            flt, {"$set": {"reviewed_at": at, "needs_review": False}}
        )
        if result.matched_count > 0:
            return "ok"
        if state_since is not None and await self._col.find_one({"patient_id": patient_id}):
            return "stale"
        return "not_found"

    async def list(
        self,
        *,
        facility_id: str | None,
        care_provider_id: str | None = None,
        is_facility_admin: bool = True,
        status: str | None = None,
        actionable: bool = False,
        modality: str | None = None,
        search: str | None = None,
        needs_review: bool | None = None,
        sort: str = "priority",
        order: int = 1,
        skip: int = 0,
        limit: int = 25,
    ) -> tuple[list[dict[str, Any]], int]:
        q: dict[str, Any] = {}
        if is_facility_admin:
            if facility_id:
                q["facility_id"] = facility_id
        elif care_provider_id:
            q["care_provider_ids"] = care_provider_id
        if status:
            q["assessment"] = status
        elif actionable:
            q["assessment"] = {"$nin": ["not_started", "responding"]}
        if modality:
            q["modality"] = modality
        if needs_review is not None:
            q["needs_review"] = needs_review
        if search:
            q["name"] = {"$regex": search, "$options": "i"}

        sort_key = sort if sort in _SORTABLE else "priority"
        direction = 1 if order >= 0 else -1
        sort_spec = [(sort_key, direction)]
        if sort_key != "patient_id":
            sort_spec.append(("patient_id", 1))
        total = await self._col.count_documents(q)
        cursor = (
            self._col.find(q, {"_id": 0})
            .sort(sort_spec)
            .skip(max(0, skip))
            .limit(limit)
        )
        rows = await cursor.to_list(length=limit)
        return rows, total
