from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.models.admin import Admin
from lib.models.associations import patient_care_provider_association
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception


async def resolve_profile_type(
    session: AsyncSession, user_id: UUID
) -> ProfileTypeEnum:
    if await session.scalar(
        select(Patient.patient_id).where(Patient.patient_id == user_id)
    ):
        return ProfileTypeEnum.PATIENT

    if await session.scalar(
        select(CareProvider.care_provider_id).where(
            CareProvider.care_provider_id == user_id
        )
    ):
        return ProfileTypeEnum.CARE_PROVIDER

    if await session.scalar(
        select(Admin.id).where(Admin.id == user_id)
    ):
        return ProfileTypeEnum.ADMIN

    raise_http_exception(
        status_code=404,
        message="User not found",
    )


async def authorize_device_access(
    *,
    session: AsyncSession,
    current_user_id: UUID,
    current_role: ProfileTypeEnum,
    target_user_id: UUID,
    target_role: ProfileTypeEnum,
):
    if current_role == ProfileTypeEnum.PATIENT:
        if current_user_id != target_user_id:
            raise_http_exception(
                status_code=403,
                message="Patients can only access their own devices",
            )

    # Care Providers
    elif current_role == ProfileTypeEnum.CARE_PROVIDER:
        if target_role == ProfileTypeEnum.PATIENT:
            is_assigned = await session.scalar(
                select(patient_care_provider_association.c.patient_id).where(
                    and_(
                        patient_care_provider_association.c.care_provider_id
                        == current_user_id,
                        patient_care_provider_association.c.patient_id
                        == target_user_id,
                    )
                )
            )
            if not is_assigned:
                raise_http_exception(
                    status_code=403,
                    message="You do not have access to this patient's devices",
                )

        elif target_role == ProfileTypeEnum.CARE_PROVIDER:
            if current_user_id != target_user_id:
                raise_http_exception(
                    status_code=403,
                    message="Care providers can only access their own devices",
                )

        elif target_role == ProfileTypeEnum.ADMIN:
            raise_http_exception(
                status_code=403,
                message="Care providers cannot access admin devices",
            )

    # Admin
    elif current_role == ProfileTypeEnum.ADMIN:
        return  # full access
