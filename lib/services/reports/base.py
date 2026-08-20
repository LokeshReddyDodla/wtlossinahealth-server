"""Shared pieces of the four report services (spec §5, slice 4).

Every modality stores reports the same way: Mongo doc keyed by
sha256(patient_id_reportType_start[_end]), full-replace upsert, queried by
patient + metadata.report_type + metadata.date_range.start. The id scheme and
the indexes live here so the four services can't drift; modality-specific
save/fetch quirks (CGM's $lookups, meal's date shim) stay in the services.
"""

from __future__ import annotations

import hashlib
from typing import Any

REPORT_COLLECTION_NAMES = (
    "cgm_reports",
    "meal_reports",
    "fitness_reports",
    "sleep_reports",
)


def report_id(
    patient_id: str,
    report_type: str,
    start_iso: str,
    end_iso: str | None = None,
) -> str:
    """Deterministic report _id. CGM custom and meal daily omit the end —
    their identity is the period start / the day."""
    parts = [patient_id, report_type, start_iso]
    if end_iso is not None:
        parts.append(end_iso)
    return hashlib.sha256("_".join(parts).encode()).hexdigest()


async def ensure_report_indexes(mongo_store: Any) -> None:
    """The universal query shape across all four collections."""
    for name in REPORT_COLLECTION_NAMES:
        await mongo_store.get_collection(name).create_index(
            [
                ("patient_id", 1),
                ("metadata.report_type", 1),
                ("metadata.date_range.start", 1),
            ],
            name="report_query_idx",
        )
