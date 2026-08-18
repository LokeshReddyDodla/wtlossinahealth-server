"""Context provider for panel recompute — identity, scope, conditions, and the
glucose frontier for one patient, from Postgres."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.database import postgres_store
from lib.models.associations import patient_care_provider_association
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


async def panel_context(patient_id: str) -> dict[str, Any]:
    async with postgres_store.get_session() as s:
        patient = (
            await s.execute(select(Patient).where(Patient.patient_id == patient_id))
        ).scalar_one_or_none()
        if patient is None:
            return {}

        dh = (
            await s.execute(
                select(PatientDiabeticHistory).where(PatientDiabeticHistory.patient_id == patient_id)
            )
        ).scalar_one_or_none()
        rh = (
            await s.execute(
                select(PatientReproductiveHealth).where(PatientReproductiveHealth.patient_id == patient_id)
            )
        ).scalar_one_or_none()

        cp_ids = list(
            (
                await s.execute(
                    select(patient_care_provider_association.c.care_provider_id).where(
                        patient_care_provider_association.c.patient_id == patient_id
                    )
                )
            ).scalars().all()
        )

        frontier_at: datetime | None = None
        for model in (PatientLibreView, PatientSinocare):
            row = (
                await s.execute(
                    select(model.last_cgm_reading_at)
                    .join(PatientConnectedApp, model.connected_app_id == PatientConnectedApp.id)
                    .where(PatientConnectedApp.patient_id == patient_id)
                    .where(model.last_cgm_reading_at.is_not(None))
                )
            ).scalars().first()
            if row is not None and (frontier_at is None or row > frontier_at):
                frontier_at = row

        last_active_at = (
            await s.execute(
                select(func.max(UserDevice.last_active_at)).where(
                    UserDevice.user_id == patient_id,
                    UserDevice.profile_type == ProfileTypeEnum.PATIENT.value,
                )
            )
        ).scalar_one_or_none()

    is_pregnant = bool((rh and rh.is_pregnant) or (dh and dh.is_pregnant))
    return _build(
        last_active_at=last_active_at,
        first_name=patient.first_name,
        last_name=patient.last_name,
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
