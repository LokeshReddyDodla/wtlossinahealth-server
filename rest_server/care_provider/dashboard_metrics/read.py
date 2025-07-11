from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID
from fastapi import Depends, HTTPException, Query, status

from lib.dependencies.auth.care_provider_auth import get_current_care_provider
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
from rest_server.care_provider.dashboard_metrics.api_schema import (
    PatientMealSchema,
)

from rest_server.response_models import SuccessResponse

from .router import router


@router.get("/total-patients", response_model=SuccessResponse)
async def total_patients_enrolled(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0),
    patient_metrics_service: PatientMetricsService = Depends(
        get_patient_metrics_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    try:
        patients = await patient_metrics_service.get_patients(
            health_facility_id=str(current_care_provider.health_facility_id),
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


@router.get("/total-patients/grouped", response_model=SuccessResponse)
async def total_patients_grouped_by_date(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    patient_metrics_service: PatientMetricsService = Depends(
        get_patient_metrics_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    try:
        grouped = await patient_metrics_service.get_patient_counts_by_date(
            health_facility_id=str(current_care_provider.health_facility_id),
            start=start,
            end=end,
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
async def meals_grouped_by_date(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    with_photos_only: bool = Query(
        False, description="Only include meals with photos"
    ),
    meal_metrics_service: MealMetricsService = Depends(
        get_meal_metrics_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    data = await meal_metrics_service.get_meal_uploads_grouped_by_date(
        health_facility_id=str(current_care_provider.health_facility_id),
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
async def macro_filtered_major_meals(
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
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    try:
        meals = await meal_metrics_service.get_macro_filtered_major_meals(
            health_facility_id=str(current_care_provider.health_facility_id),
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


@router.get("/steps-threshold")
async def get_patients_by_step_threshold(
    steps_op: str = Query(
        "lt", description="Comparison operator: lt, lte, gt, gte, eq"
    ),
    steps_value: int = Query(
        1000, description="Step count value to compare against"
    ),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    fitness_metrics_service: FitnessMetricsService = Depends(
        get_fitness_metrics_service
    ),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):

    try:
        patients = (
            await fitness_metrics_service.get_patients_by_step_threshold(
                health_facility_id=str(
                    current_care_provider.health_facility_id
                ),
                steps_op=steps_op,
                steps_value=steps_value,
                start_date=start_date,
                end_date=end_date,
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
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    patients = await smbg_metrics_service.get_active_patients(
        health_facility_id=str(current_care_provider.health_facility_id),
        days=days,
    )

    return SuccessResponse(
        message=f"{len(patients)} patients with active SMBG in past {days} days",
        data=[PatientSchema.from_orm(p) for p in patients],
    )


@router.get(
    "/patients-hyper-duration",
    response_model=SuccessResponse,
)
async def patients_with_hyper_duration(
    min_duration_minutes: int = Query(45, ge=1),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    cgm_metrics_service: CGMMetricsService = Depends(get_cgm_metrics_service),
    current_care_provider: CareProviderModel = Depends(
        get_current_care_provider(
            CareProviderPermissionAction.READ,
            CareProviderFeature.HEALTH_FACILITY,
        )
    ),
):
    try:
        results = await cgm_metrics_service.get_patients_with_time_above_range(
            health_facility_id=str(current_care_provider.health_facility_id),
            min_duration_minutes=min_duration_minutes,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

        return SuccessResponse(
            message="Patients with time above range fetched successfully",
            data=results,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
