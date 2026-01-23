from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.associations import patient_care_provider_association
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.models.patient import Patient as PatientModel
from lib.utils.postgres_session_decorator import with_postgres_session


class CareProviderAccessService:
    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store

    @with_postgres_session
    async def is_patient_assigned(
        self,
        care_provider_id: UUID,
        patient_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> bool:
        care_provider = await postgres_session.scalar(
            select(CareProviderModel).where(
                CareProviderModel.care_provider_id == care_provider_id
            )
        )

        if not care_provider:
            return False


        # Admin rule
        if str(care_provider.role).lower() == "admin":
            patient = await postgres_session.scalar(
                select(PatientModel).where(
                    PatientModel.patient_id == patient_id
                )
            )

            if (
                patient
                and care_provider.health_facility_id
                and patient.health_facility_id
                and care_provider.health_facility_id == patient.health_facility_id
            ):
                return True


        # Assignment rule
        is_assigned = await postgres_session.scalar(
            select(patient_care_provider_association.c.patient_id).where(
                and_(
                    patient_care_provider_association.c.care_provider_id
                    == care_provider_id,
                    patient_care_provider_association.c.patient_id == patient_id,
                )
            )
        )

        return bool(is_assigned)

