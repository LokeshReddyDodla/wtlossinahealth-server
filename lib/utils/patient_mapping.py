from typing import List, Dict, Callable, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception
from fastapi import status
from lib.models.associations import patient_care_provider_association
from sqlalchemy.orm import selectinload


async def map_patients_to_reports(
    reports: List[Dict],
    postgres_session: AsyncSession,
    extract_patient_id: Callable[[Dict], str],
    enrich_payload: Callable[[Dict, Patient], Dict],
    health_facility_id: Optional[str] = None,
    care_provider_id: Optional[str] = None,
    is_facility_admin: bool = False,
) -> List[Dict]:
    if not reports:
        return []

    # Get unique patient_ids
    # patient_ids = list({extract_patient_id(r) for r in reports})
    patient_ids = list(
        {extract_patient_id(r) for r in reports if "patient_id" in r}
    )

    stmt = (
        select(Patient)
        .options(selectinload(Patient.diabetic_history))
        .where(Patient.patient_id.in_(patient_ids))
    )

    if health_facility_id and is_facility_admin:
        stmt = stmt.where(Patient.health_facility_id == health_facility_id)
    elif care_provider_id:
        stmt = stmt.join(
            patient_care_provider_association,
            Patient.patient_id
            == patient_care_provider_association.c.patient_id,
        ).where(
            patient_care_provider_association.c.care_provider_id
            == care_provider_id
        )

    try:
        result = await postgres_session.execute(stmt)
        patients = {p.patient_id: p for p in result.scalars().all()}

        enriched = []
        for report in reports:
            patient_id = report.get("patient_id")
            if not patient_id:
                continue

            pid = UUID(patient_id)
            if patient := patients.get(pid):  # type: ignore
                enriched.append(enrich_payload(report, patient))

        return enriched

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to map patient data",
            detail=str(e),
        )
