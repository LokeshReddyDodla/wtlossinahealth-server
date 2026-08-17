"""Mongo store for `patient_panel_signal` — the materialized read model.

One row per patient (upserted on recompute), read scoped + filtered + sorted +
paginated in a single query. Rows carry facility_id + care_provider_ids so
visibility is one indexed filter, never a per-request join.
"""

from __future__ import annotations

from typing import Any

from lib.schemas.patient_panel_signal import PatientPanelSignal

# Only these fields may drive a sort — guards against arbitrary client input
# hitting an unindexed sort.
_SORTABLE = {
    "priority", "name", "tir_pct", "avg_glucose", "cv_pct", "gmi",
    "below_70_pct", "above_180_pct", "a1c", "adherence_pct",
    "last_glucose_at", "last_active_at", "computed_at",
}


class PatientPanelStore:
    def __init__(self, collection):
        self._col = collection

    async def ensure_indexes(self) -> None:
        """Idempotent; called once at startup like the other Mongo services."""
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

    async def upsert(self, signal: PatientPanelSignal) -> None:
        # mode="json" so enums serialise to their str value and datetimes to ISO —
        # bson can't store Enum members, and ISO datetimes still sort correctly.
        doc = signal.model_dump(mode="json")
        await self._col.replace_one({"patient_id": signal.patient_id}, doc, upsert=True)

    async def list(
        self,
        *,
        facility_id: str | None,
        care_provider_id: str | None = None,
        is_facility_admin: bool = True,
        status: str | None = None,
        modality: str | None = None,
        search: str | None = None,
        sort: str = "priority",
        order: int = 1,
        skip: int = 0,
        limit: int = 25,
    ) -> tuple[list[dict[str, Any]], int]:
        q: dict[str, Any] = {}
        if facility_id:
            q["facility_id"] = facility_id
        # A non-admin provider sees only patients they're assigned to.
        if care_provider_id and not is_facility_admin:
            q["care_provider_ids"] = care_provider_id
        if status:
            q["assessment"] = status
        if modality:
            q["modality"] = modality
        if search:
            q["name"] = {"$regex": search, "$options": "i"}

        sort_key = sort if sort in _SORTABLE else "priority"
        total = await self._col.count_documents(q)
        cursor = (
            self._col.find(q, {"_id": 0})
            .sort(sort_key, 1 if order >= 0 else -1)
            .skip(max(0, skip))
            .limit(limit)
        )
        rows = await cursor.to_list(length=limit)
        return rows, total
