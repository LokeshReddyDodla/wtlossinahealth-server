from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from fastapi import Depends, Query, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.database import get_postgres_session
from lib.dependencies.device_access import (
    authorize_device_access,
    resolve_profile_type,
)
from lib.models.associations import patient_care_provider_association
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception


@dataclass
class ReportAccessInfo:
    target_patient_id: UUID
    target_role: ProfileTypeEnum
    current_user_id: UUID
    current_role: ProfileTypeEnum


async def authorize_report_access(
    *,
    session: AsyncSession,
    current_user_id: UUID,
    current_role: ProfileTypeEnum,
    target_patient_id: UUID,
    target_role: ProfileTypeEnum,
):
    """
    Authorize access to patient reports based on roles.
    
    Rules:
    - Patients can only access their own reports
    - Care providers can access reports for:
      * Patients assigned to them directly, OR
      * Patients in the same health facility (if care provider is facility admin)
    - Admins have full access
    """
    if current_role == ProfileTypeEnum.PATIENT:
        if current_user_id != target_patient_id:
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Patients can only access their own reports",
            )

    # Care Providers
    elif current_role == ProfileTypeEnum.CARE_PROVIDER:
        if target_role == ProfileTypeEnum.PATIENT:
            # Check if care provider is admin and shares the same health facility
            care_provider = await session.scalar(
                select(CareProvider).where(
                    CareProvider.care_provider_id == current_user_id
                )
            )
            
            if care_provider and str(care_provider.role).lower() == "admin":
                patient = await session.scalar(
                    select(Patient).where(Patient.patient_id == target_patient_id)
                )
                
                # Allow access if both have the same health facility and it's not None
                if (
                    patient
                    and care_provider.health_facility_id is not None
                    and patient.health_facility_id is not None
                    and care_provider.health_facility_id == patient.health_facility_id
                ):
                    return
            
            # Fall back to checking direct assignment via association table
            is_assigned = await session.scalar(
                select(patient_care_provider_association.c.patient_id).where(
                    and_(
                        patient_care_provider_association.c.care_provider_id
                        == current_user_id,
                        patient_care_provider_association.c.patient_id
                        == target_patient_id,
                    )
                )
            )
            if not is_assigned:
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="You do not have access to this patient's reports",
                )

    # Admin
    elif current_role == ProfileTypeEnum.ADMIN:
        return  # full access


async def get_report_access_info(
    patient_id: Optional[str] = Query(
        None,
        description="Patient ID to fetch reports for (optional, defaults to authenticated user)",
    ),
    token_data: tuple = Depends(get_current_user),
    session: AsyncSession = Depends(get_postgres_session),
) -> ReportAccessInfo:
    """
    Dependency function that validates and resolves patient access for report endpoints.
    
    This function:
    1. Extracts current user info from token
    2. Validates that care providers provide patient_id
    3. Resolves target patient_id (defaults to current user if not provided)
    4. Validates that target user is a patient
    5. Authorizes access based on roles
    
    Args:
        patient_id: Optional patient ID (required for care providers)
        token_data: Tuple of (user_id, role) from get_current_user
        session: Database session
        
    Returns:
        ReportAccessInfo with resolved patient information
        
    Raises:
        HTTPException: If validation or authorization fails
    """
    current_user_id, role_value = token_data
    current_role = ProfileTypeEnum(role_value)

    # Care providers must provide patient_id (they don't have their own reports)
    if current_role == ProfileTypeEnum.CARE_PROVIDER and not patient_id:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="patient_id is required for care providers",
        )

    # Determine target patient_id (default to authenticated user if not provided)
    try:
        target_patient_id = UUID(patient_id) if patient_id else UUID(current_user_id)
    except ValueError as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Invalid patient ID format",
            detail=str(e),
        )

    # Resolve the profile type of the target user
    target_role = await resolve_profile_type(session, target_patient_id)

    # Reports are only for patients
    if target_role != ProfileTypeEnum.PATIENT:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Reports are only available for patients",
        )

    # Authorize device access based on roles
    await authorize_device_access(
        session=session,
        current_user_id=UUID(current_user_id),
        current_role=current_role,
        target_user_id=target_patient_id,
        target_role=target_role,
    )

    # Authorize report access based on roles
    await authorize_report_access(
        session=session,
        current_user_id=UUID(current_user_id),
        current_role=current_role,
        target_patient_id=target_patient_id,
        target_role=target_role,
    )

    return ReportAccessInfo(
        target_patient_id=target_patient_id,
        target_role=target_role,
        current_user_id=UUID(current_user_id),
        current_role=current_role,
    )
