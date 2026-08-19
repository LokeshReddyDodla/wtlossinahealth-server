"""GET /patients/data-richness — top patients by total data volume across all DBs."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import Depends, Query

from lib.core.constants import ProfileTypeEnum
from lib.core.container import container
from lib.core.clickhouse_store import ClickHouseStore
from lib.core.mongo_store import MongoStore
from lib.core.postgres_store import PostgresStore
from lib.dependencies.actor import Actor, get_current_actor
from lib.models.patient import Patient
from lib.models.patient_meal import PatientMeal
from lib.models.sleep_checkin import SleepCheckin
from lib.models.mood_entry import MoodEntry
from lib.models.symptom_entry import SymptomEntry
from lib.models.patient_smbg import PatientSMBG
from lib.models.patient_prescription import PatientPrescription
from lib.models.patient_medication import PatientMedication
from lib.models.gamification import DailyTask
from lib.models.patient_report import PatientReport
from rest_server.response_models import SuccessResponse
from sqlalchemy import func, select

from .router import router

logger = logging.getLogger(__name__)


@router.get(
    "/data-richness",
    response_model=SuccessResponse,
)
async def get_data_richness(
    limit: int = Query(10, ge=1, le=50),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.ADMIN],
        )
    ),
):
    """Top patients by total data volume across PostgreSQL, ClickHouse, and MongoDB. Admin only."""
    store = container.resolve(PostgresStore)
    ch = container.resolve(ClickHouseStore)
    mongo = container.resolve(MongoStore)

    # All three DB queries in parallel
    pg_counts, ch_counts, mongo_counts, patient_names = await asyncio.gather(
        _count_postgres(store),
        asyncio.get_event_loop().run_in_executor(None, _count_clickhouse, ch),
        _count_mongo(mongo),
        _load_patient_names(store),
    )

    # Merge all counts
    totals: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0, "breakdown": {}})

    for source_name, counts in [("postgres", pg_counts), ("clickhouse", ch_counts), ("mongo", mongo_counts)]:
        for pid, breakdown in counts.items():
            for key, count in breakdown.items():
                totals[pid]["breakdown"][key] = totals[pid]["breakdown"].get(key, 0) + count
                totals[pid]["total"] += count

    # Sort by total, take top N
    ranked = sorted(totals.items(), key=lambda x: x[1]["total"], reverse=True)[:limit]

    result = []
    for pid, data in ranked:
        result.append({
            "patient_id": pid,
            "patient_name": patient_names.get(pid, "Unknown"),
            "total": data["total"],
            "breakdown": data["breakdown"],
        })

    return SuccessResponse(
        message=f"Top {len(result)} patients by data volume",
        data=result,
    )


async def _count_postgres(store: PostgresStore) -> dict[str, dict[str, int]]:
    """Count rows per patient across PostgreSQL tables."""
    tables = [
        ("meals", PatientMeal),
        ("sleep_checkins", SleepCheckin),
        ("mood_entries", MoodEntry),
        ("symptom_entries", SymptomEntry),
        ("smbg_readings", PatientSMBG),
        ("prescriptions", PatientPrescription),
        ("medications", PatientMedication),
        ("tasks_completed", DailyTask),
        ("reports", PatientReport),
    ]

    counts: dict[str, dict[str, int]] = defaultdict(dict)

    async with store.get_session() as session:
        for label, model in tables:
            query = (
                select(model.patient_id, func.count().label("cnt"))
                .group_by(model.patient_id)
            )
            if label == "tasks_completed":
                query = query.where(DailyTask.status == "completed")

            result = await session.execute(query)
            for row in result.all():
                pid = str(row.patient_id)
                counts[pid][label] = row.cnt

    return dict(counts)


def _count_clickhouse(ch: ClickHouseStore) -> dict[str, dict[str, int]]:
    """Count rows per patient across ClickHouse tables."""
    counts: dict[str, dict[str, int]] = defaultdict(dict)

    ch_tables = [
        ("cgm_readings", "aihealth.cgm_data"),
        ("fitness_data", "aihealth.fitness_data"),
        ("sleep_data", "aihealth.sleep_data"),
        ("vitals_data", "aihealth.vitals_data"),
    ]

    for label, table in ch_tables:
        try:
            rows = ch.query_data(
                f"SELECT patient_id, count() as cnt FROM {table} GROUP BY patient_id"
            )
            for pid, cnt in rows:
                counts[pid][label] = cnt
        except Exception:
            logger.debug("ClickHouse table %s not available", table)

    return dict(counts)


async def _count_mongo(mongo: MongoStore) -> dict[str, dict[str, int]]:
    """Count documents per patient across MongoDB collections."""
    counts: dict[str, dict[str, int]] = defaultdict(dict)

    collections = [
        ("patient_documents", "patient_documents", "patient_id"),
        ("proactive_insights", "ai_proactive_insights", "patient_id"),
        ("cgm_reports", "cgm_reports", "patient_id"),
        ("fitness_reports", "fitness_reports", "patient_id"),
        ("sleep_reports", "sleep_reports", "patient_id"),
        ("meal_reports", "meal_reports", "patient_id"),
    ]

    for label, collection_name, id_field in collections:
        try:
            collection = mongo.get_collection(collection_name)
            pipeline = [
                {"$group": {"_id": f"${id_field}", "count": {"$sum": 1}}},
            ]
            async for doc in collection.aggregate(pipeline):
                pid = str(doc["_id"])
                counts[pid][label] = doc["count"]
        except Exception:
            logger.debug("MongoDB collection %s not available", collection_name)

    return dict(counts)


async def _load_patient_names(store: PostgresStore) -> dict[str, str]:
    """Load patient names for display."""
    async with store.get_session() as session:
        result = await session.execute(
            select(Patient.patient_id, Patient.first_name, Patient.last_name)
        )
        return {
            str(row.patient_id): f"{row.first_name or ''} {row.last_name or ''}".strip()
            for row in result.all()
        }
