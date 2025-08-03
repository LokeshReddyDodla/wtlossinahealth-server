from typing import List, Dict, Callable
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception
from fastapi import status


async def map_patients_to_reports(
    reports: List[Dict],
    health_facility_id: str,
    postgres_session: AsyncSession,
    extract_patient_id: Callable[[Dict], str],
    enrich_payload: Callable[[Dict, Patient], Dict],
) -> List[Dict]:
    if not reports:
        return []

    # Get unique patient_ids
    patient_ids = list({extract_patient_id(r) for r in reports})

    stmt = select(Patient).where(
        Patient.patient_id.in_(patient_ids),
        Patient.health_facility_id == health_facility_id,
    )

    try:
        result = await postgres_session.execute(stmt)
        patients = {p.patient_id: p for p in result.scalars().all()}

        enriched = []
        for report in reports:
            pid = UUID(extract_patient_id(report))
            if patient := patients.get(pid):  # type: ignore
                enriched.append(enrich_payload(report, patient))

        return enriched

    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to map patient data",
            detail=str(e),
        )
