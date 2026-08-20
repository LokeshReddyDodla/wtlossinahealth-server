"""Context provider for panel recompute — identity, scope, conditions, and the
glucose frontier for one patient, from Postgres."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.database import postgres_store
from lib.models.associations import patient_care_provider_association
from lib.models.care_intent import CareIntent
from lib.models.care_intent_event import CareIntentEvent
from lib.models.patient import Patient
from lib.models.patient_connected_app import (
    PatientConnectedApp,
    PatientLibreView,
    PatientSinocare,
)
from lib.models.patient_diabetic_history import PatientDiabeticHistory
from lib.models.patient_reproductive_health import PatientReproductiveHealth
from lib.models.user_device import UserDevice
from lib.schemas.patient_panel_signal import GlucoseSource, Modality

_CGM_STALE_DAYS = 2


def _age(dob: date | None, now: datetime) -> int | None:
    if dob is None:
        return None
    return now.year - dob.year - ((now.month, now.day) < (dob.month, dob.day))


def _build(
    *,
    first_name: str | None,
    last_name: str | None,
    dob: date | None,
    gender: str | None,
    profile_picture: str | None = None,
    weight_kg: float | None,
    created_at: datetime | None,
    diabetes_type: str | None,
    diabetes_years: float | None,
    is_pregnant: bool,
    pregnancy_weeks: int | None,
    care_provider_ids: list[str],
    facility_id: str | None,
    frontier_at: datetime | None,
    frontier_source: GlucoseSource,
    last_active_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)

    conditions: list[str] = []
    if diabetes_type:
        years = f" {diabetes_years:g}y" if diabetes_years else ""
        conditions.append(f"{diabetes_type}{years}")
    if is_pregnant:
        conditions.insert(0, f"GDM {pregnancy_weeks}wk" if pregnancy_weeks else "Pregnant")

    glucose_expected = bool(diabetes_type)

    days_ago: float | None = None
    sync_stale = False
    if frontier_at is not None:
        days_ago = (now - _as_utc(frontier_at)).days
        sync_stale = days_ago > _CGM_STALE_DAYS

    if frontier_at is not None:
        modality = Modality.CGM
    elif glucose_expected:
        modality = Modality.LABS
    elif weight_kg is not None:
        modality = Modality.WEIGHT
    else:
        modality = Modality.NONE

    return {
        "name": f"{first_name or ''} {last_name or ''}".strip(),
        "profile_picture": profile_picture,
        "age": _age(dob, now),
        "sex": gender,
        "conditions": conditions,
        "modality": modality,
        "is_pregnant": is_pregnant,
        "glucose_expected": glucose_expected,
        "enrolled_days": (now - _as_utc(created_at)).days if created_at else None,
        "has_any_data": frontier_at is not None or weight_kg is not None,
        "care_provider_ids": care_provider_ids,
        "facility_id": facility_id,
        "last_glucose_at": frontier_at,
        "last_glucose_source": frontier_source,
        "last_glucose_days_ago": days_ago,
        "glucose_sync_stale": sync_stale,
        "glucose_sync_stale_days": int(days_ago) if sync_stale and days_ago is not None else None,
        "last_active_at": last_active_at,
    }


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _frontier_subquery(model):
    return (
        select(func.max(model.last_cgm_reading_at))
        .join(PatientConnectedApp, model.connected_app_id == PatientConnectedApp.id)
        .where(PatientConnectedApp.patient_id == Patient.patient_id)
        .scalar_subquery()
    )


def _adherence_count_subquery(event_status: str, since: date):
    return (
        select(func.count())
        .select_from(CareIntentEvent)
        .join(CareIntent, CareIntentEvent.care_intent_id == CareIntent.care_intent_id)
        .where(
            CareIntent.patient_id == Patient.patient_id,
            CareIntent.status == "active",
            CareIntentEvent.event_date >= since,
            CareIntentEvent.status == event_status,
        )
        .scalar_subquery()
    )


async def panel_context(patient_id: str) -> dict[str, Any]:
    # Recompute runs with high concurrency, so the whole context is one
    # round-trip — the connection is held for one query, not seven.
    adherence_since = datetime.now(timezone.utc).date() - timedelta(days=30)
    stmt = (
        select(
            Patient,
            PatientDiabeticHistory,
            PatientReproductiveHealth,
            select(func.array_agg(patient_care_provider_association.c.care_provider_id))
            .where(patient_care_provider_association.c.patient_id == Patient.patient_id)
            .scalar_subquery(),
            select(func.max(UserDevice.last_active_at))
            .where(
                UserDevice.user_id == Patient.patient_id,
                UserDevice.profile_type == ProfileTypeEnum.PATIENT.value,
            )
            .scalar_subquery(),
            _frontier_subquery(PatientLibreView),
            _frontier_subquery(PatientSinocare),
            _adherence_count_subquery("followed", adherence_since),
            _adherence_count_subquery("missed", adherence_since),
        )
        .outerjoin(PatientDiabeticHistory, PatientDiabeticHistory.patient_id == Patient.patient_id)
        .outerjoin(PatientReproductiveHealth, PatientReproductiveHealth.patient_id == Patient.patient_id)
        .where(Patient.patient_id == patient_id)
    )
    async with postgres_store.get_session() as s:
        row = (await s.execute(stmt)).first()

    if row is None:
        return {}
    patient, dh, rh, cp_ids, last_active_at, lv_frontier, sino_frontier, followed, missed = row

    frontier_candidates = [f for f in (lv_frontier, sino_frontier) if f is not None]
    frontier_at = max(frontier_candidates) if frontier_candidates else None

    adherence_pct: int | None = None
    decided = (followed or 0) + (missed or 0)
    if decided:
        adherence_pct = round(100 * (followed or 0) / decided)
    cp_ids = cp_ids or []

    is_pregnant = bool((rh and rh.is_pregnant) or (dh and dh.is_pregnant))
    ctx = _build(
        last_active_at=last_active_at,
        first_name=patient.first_name,
        last_name=patient.last_name,
        profile_picture=patient.profile_picture,
        dob=patient.dob,
        gender=patient.gender,
        weight_kg=patient.weight_kg,
        created_at=patient.created_at,
        diabetes_type=dh.type_of_diabetes if dh else None,
        diabetes_years=dh.years_with_diabetes if dh else None,
        is_pregnant=is_pregnant,
        pregnancy_weeks=(rh.pregnancy_weeks if rh else None) or (dh.pregnancy_weeks if dh else None),
        care_provider_ids=[str(c) for c in cp_ids],
        facility_id=str(patient.health_facility_id) if patient.health_facility_id else None,
        frontier_at=frontier_at,
        frontier_source=GlucoseSource.CGM if frontier_at is not None else GlucoseSource.NONE,
    )
    ctx["adherence_pct"] = adherence_pct
    return ctx
