from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple, Union
from uuid import UUID
from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.auth.flexible_auth import get_current_user_flexible
from lib.models.admin import Admin
from lib.dependencies.service_dependencies import (
    get_cgm_metrics_service,
    get_fitness_metrics_service,
    get_meal_metrics_service,
    get_patient_metrics_service,
    get_smbg_metrics_service,
)
from lib.models.care_provider import CareProvider as CareProviderModel
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.patient import Patient as PatientSchema

from lib.services.dashboard_metrics.cgm_metrics_service import (
    CGMMetricsService,
)
from lib.services.dashboard_metrics.fitneess_metrics_service import (
    FitnessMetricsService,
)
from lib.services.dashboard_metrics.meal_metrics_service import (
    MealMetricsService,
)
from lib.services.dashboard_metrics.smbg_metrics_service import (
    SMBGMetricsService,
)
from lib.services.dashboard_metrics.patient_metrics_service import (
    PatientMetricsService,
)
from lib.services.package_service import PackageService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.dashboard_metrics.api_schema import (
    PatientMealSchema,
)

from rest_server.response_models import SuccessResponse

from .router import router


def resolve_patient_scope(
    current_user: Union[CareProviderModel, Admin],
) -> Tuple[Optional[str], Optional[str], bool]:
    if isinstance(current_user, CareProviderModel):
        return (
            (
                str(current_user.health_facility_id)
                if current_user.health_facility_id
                else None
            ),
            (
                str(current_user.care_provider_id)
                if current_user.care_provider_id
                else None
            ),
            current_user.is_admin,
        )

    # Global admin
    return None, None, False


@router.get("/patients/active/grouped", response_model=SuccessResponse)
async def get_active_patients_grouped(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    patient_metrics_service: PatientMetricsService = Depends(
        get_patient_metrics_service
    ),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    try:
        health_facility_id, care_provider_id, is_facility_admin = (
            resolve_patient_scope(current_user)
        )

        grouped = await patient_metrics_service.get_active_patients_by_date(
            health_facility_id=health_facility_id,
            care_provider_id=care_provider_id,
            is_facility_admin=is_facility_admin,
            start=start,
            end=end,
        )

        return SuccessResponse(
            message="Active patients grouped by date",
            data=grouped,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/patients/enrolled", response_model=SuccessResponse)
async def get_enrolled_patients(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0),
    patient_metrics_service: PatientMetricsService = Depends(
        get_patient_metrics_service
    ),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    try:
        health_facility_id, care_provider_id, is_facility_admin = (
            resolve_patient_scope(current_user)
        )

        patients = await patient_metrics_service.get_enrolled_patients(
            health_facility_id=health_facility_id,
            care_provider_id=care_provider_id,
            is_facility_admin=is_facility_admin,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message="Total enrolled patients fetched successfully",
            data=[PatientSchema.from_orm(p) for p in patients],
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/patients/enrolled/grouped", response_model=SuccessResponse)
async def get_enrolled_patients_grouped(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    patient_metrics_service: PatientMetricsService = Depends(
        get_patient_metrics_service
    ),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    try:
        health_facility_id, care_provider_id, is_facility_admin = (
            resolve_patient_scope(current_user)
        )

        grouped = (
            await patient_metrics_service.get_enrolled_patient_counts_by_date(
                health_facility_id=health_facility_id,
                care_provider_id=care_provider_id,
                is_facility_admin=is_facility_admin,
                start=start,
                end=end,
            )
        )

        return SuccessResponse(
            message="Patients grouped by date",
            data=grouped,
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )


@router.get("/meals/grouped", response_model=SuccessResponse)
async def get_meals_grouped(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    with_photos_only: bool = Query(
        False, description="Only include meals with photos"
    ),
    meal_metrics_service: MealMetricsService = Depends(
        get_meal_metrics_service
    ),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    health_facility_id, care_provider_id, is_facility_admin = (
        resolve_patient_scope(current_user)
    )
    data = await meal_metrics_service.get_meal_uploads_grouped_by_date(
        health_facility_id=health_facility_id,
        care_provider_id=care_provider_id,
        is_facility_admin=is_facility_admin,
        start=start,
        end=end,
        with_photos_only=with_photos_only,
    )
    return SuccessResponse(
        message="Meal uploads grouped by date",
        data=data,
    )


class ComparisonOperator(str, Enum):
    lt = "lt"
    lte = "lte"
    gt = "gt"
    gte = "gte"
    eq = "eq"


@router.get("/meals/filter-macro", response_model=SuccessResponse)
async def get_macro_filtered_meals(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    protein_threshold: Optional[float] = Query(None),
    protein_op: Optional[ComparisonOperator] = Query(None),
    fiber_threshold: Optional[float] = Query(None),
    fiber_op: Optional[ComparisonOperator] = Query(None),
    carbs_threshold: Optional[float] = Query(None),
    carbs_op: Optional[ComparisonOperator] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0),
    meal_metrics_service: MealMetricsService = Depends(
        get_meal_metrics_service
    ),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    health_facility_id, care_provider_id, is_facility_admin = (
        resolve_patient_scope(current_user)
    )
    try:
        meals = await meal_metrics_service.get_macro_filtered_major_meals(
            health_facility_id=health_facility_id,
            care_provider_id=care_provider_id,
            is_facility_admin=is_facility_admin,
            start=start,
            end=end,
            protein_threshold=protein_threshold,
            protein_op=protein_op,
            fiber_threshold=fiber_threshold,
            fiber_op=fiber_op,
            carbs_threshold=carbs_threshold,
            carbs_op=carbs_op,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message="Filtered major meals fetched successfully",
            data=[PatientMealSchema.from_orm(meal) for meal in meals],
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Unexpected error fetching low protein and fiber major meals",
            detail=str(e),
        )


@router.get("/fitness/steps-threshold")
async def get_patients_by_step_threshold(
    steps_op: str = Query(
        "lt", description="Comparison operator: lt, lte, gt, gte, eq"
    ),
    steps_value: int = Query(
        1000, description="Step count value to compare against"
    ),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    fitness_metrics_service: FitnessMetricsService = Depends(
        get_fitness_metrics_service
    ),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    health_facility_id, care_provider_id, is_facility_admin = (
        resolve_patient_scope(current_user)
    )

    try:
        patients = (
            await fitness_metrics_service.get_patients_by_step_threshold(
                health_facility_id=health_facility_id,
                care_provider_id=care_provider_id,
                is_facility_admin=is_facility_admin,
                steps_op=steps_op,
                steps_value=steps_value,
                start=start,
                end=end,
                limit=limit,
                offset=offset,
            )
        )

        return SuccessResponse(
            message="Patients filtered by step threshold fetched successfully",
            data=patients,
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Unexpected error fetching patients with low steps",
            detail=str(e),
        )


@router.get("/active-smbg", response_model=SuccessResponse)
async def get_active_smbg_patients(
    days: int = Query(3, ge=1, le=30),
    smbg_metrics_service: SMBGMetricsService = Depends(
        get_smbg_metrics_service
    ),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    health_facility_id, care_provider_id, is_facility_admin = (
        resolve_patient_scope(current_user)
    )
    patients = await smbg_metrics_service.get_active_patients(
        health_facility_id=health_facility_id,
        care_provider_id=care_provider_id,
        is_facility_admin=is_facility_admin,
        days=days,
    )

    return SuccessResponse(
        message=f"{len(patients)} patients with active SMBG in past {days} days",
        data=[PatientSchema.from_orm(p) for p in patients],
    )


@router.get("/cgm/hyper-patients", response_model=SuccessResponse)
async def get_patients_with_hyper_events(
    days: int = Query(3, ge=1, le=90),
    min_duration_minutes: float = Query(45, ge=1),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    cgm_metrics_service: CGMMetricsService = Depends(get_cgm_metrics_service),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    health_facility_id, care_provider_id, is_facility_admin = (
        resolve_patient_scope(current_user)
    )
    try:
        end = datetime.now()
        start = end - timedelta(days=days)

        patients = await cgm_metrics_service.find_patients_with_hyper_events(
            start=start,
            end=end,
            min_duration_minutes=min_duration_minutes,
            health_facility_id=health_facility_id,
            care_provider_id=care_provider_id,
            is_facility_admin=is_facility_admin,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message=f"{len(patients)} patients with hyperglycemia events ≥ {min_duration_minutes} mins in past {days} days",
            data=patients,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Unexpected error fetching patients with hyperglycemia events",
            detail=str(e),
        )


@router.get("/cgm/hypo-patients", response_model=SuccessResponse)
async def get_patients_with_hypo_events(
    days: int = Query(7, ge=1, le=60),
    min_duration_minutes: float = Query(20, ge=1),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    cgm_metrics_service: CGMMetricsService = Depends(get_cgm_metrics_service),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    health_facility_id, care_provider_id, is_facility_admin = (
        resolve_patient_scope(current_user)
    )
    try:
        end = datetime.now()
        start = end - timedelta(days=days)

        patients = await cgm_metrics_service.find_patients_with_hypo_events(
            start=start,
            end=end,
            min_duration_minutes=min_duration_minutes,
            health_facility_id=health_facility_id,
            care_provider_id=care_provider_id,
            is_facility_admin=is_facility_admin,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message=f"{len(patients)} patients with hypoglycemia events ≥ {min_duration_minutes} mins in past {days} days",
            data=patients,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Unexpected error fetching patients with hypoglycemia events",
            detail=str(e),
        )


@router.get("/cgm/high-gv-patients", response_model=SuccessResponse)
async def get_patients_with_high_gv(
    days: int = Query(7, ge=1, le=60),
    gv_threshold: float = Query(20, ge=0),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    cgm_metrics_service: CGMMetricsService = Depends(get_cgm_metrics_service),
    current_user: Union[CareProviderModel, Admin] = Depends(
        get_current_user_flexible(
            allowed_types=[
                ProfileTypeEnum.CARE_PROVIDER,
                ProfileTypeEnum.ADMIN,
            ],
            care_provider_action=CareProviderPermissionAction.READ,
            care_provider_feature=CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    health_facility_id, care_provider_id, is_facility_admin = (
        resolve_patient_scope(current_user)
    )
    try:
        end = datetime.now()
        start = end - timedelta(days=days)

        patients = await cgm_metrics_service.find_patients_with_high_glucose_variability(
            start=start,
            end=end,
            gv_threshold=gv_threshold,
            health_facility_id=health_facility_id,
            care_provider_id=care_provider_id,
            is_facility_admin=is_facility_admin,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message=f"{len(patients)} patients with GV > {gv_threshold} in past {days} days",
            data=patients,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Unexpected error fetching patients with high glucose variability",
            detail=str(e),
        )
