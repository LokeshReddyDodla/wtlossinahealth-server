import asyncio
from typing import List, Literal, Optional

from fastapi import Depends, HTTPException, Query, status

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.service_dependencies import (
    get_patient_enrichment_service,
    get_patient_query_service,
)
from lib.queries.patient_query import PatientQuery
from lib.schemas.care_provider import CareProvider as CareProviderSchema
from lib.schemas.health_facility import HealthFacility as HealthFacilitySchema
from lib.schemas.patient import Patient as PatientSchema
from lib.schemas.patient_package_assignment import (
    PatientPackageAssignmentWithDetail as PatientPackageAssignmentWithDetailSchema,
)
from lib.services.patient_enrichment_service import PatientEnrichmentService
from lib.services.patient_query_service import PatientQueryService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from rest_server.v1.utils import (
    get_effective_care_provider_id,
    get_effective_health_facility_id,
)

from .router import router


@router.get("", response_model=SuccessResponse)
async def list_patients(
    limit: Optional[int] = Query(None, description="Limit number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    search: Optional[str] = Query(None, description="Search term"),
    age: Optional[List[str]] = Query(None, description="Age filter"),
    gender: Optional[List[str]] = Query(None, description="Gender filter"),
    monitoring_method: Optional[List[str]] = Query(
        None, description="Monitoring method filter"
    ),
    package: Optional[List[str]] = Query(None, description="Package filter"),
    connected_apps: Optional[List[str]] = Query(
        None, description="Connected apps filter"
    ),
    diagnosis: Optional[List[str]] = Query(
        None, description="Diabetes type filter (T1/T2/PRE/GESTATIONAL/...)"
    ),
    prescription: Optional[List[str]] = Query(
        None, description="Prescription status filter (draft/confirmed)"
    ),
    medication: Optional[List[str]] = Query(
        None, description="Medication filter (on/off active meds)"
    ),
    pregnancy: Optional[List[str]] = Query(
        None, description="Pregnancy filter (pregnant)"
    ),
    activity: Optional[List[str]] = Query(
        None, description="Activity recency filter (active_7d/active_30d/inactive_30d/never)"
    ),
    order_by: Optional[
        Literal[
            "first_name",
            "last_name",
            "email",
            "created_at",
            "age",
            "last_active_at",
        ]
    ] = Query(None, description="Order by field"),
    order: Literal["asc", "desc"] = Query("desc", description="Order direction"),
    query_service: PatientQueryService = Depends(get_patient_query_service),
    enrichment_service: PatientEnrichmentService = Depends(
        get_patient_enrichment_service
    ),
    current_actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[
                ProfileTypeEnum.ADMIN,
                ProfileTypeEnum.CARE_PROVIDER,
            ],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
):
    try:
        hf_id = get_effective_health_facility_id(current_actor)
        cp_id = get_effective_care_provider_id(current_actor)

        query = PatientQuery(
            limit=limit,
            offset=offset,
            search=search,
            age=age,
            gender=gender,
            package=package,
            connected_apps=connected_apps,
            monitoring_method=monitoring_method,
            diagnosis=diagnosis,
            prescription=prescription,
            medication=medication,
            pregnancy=pregnancy,
            activity=activity,
            health_facility_id=hf_id,
            care_provider_id=cp_id,
            order_by=order_by,
            order=order,
        )

        # Fetch patients and total count in parallel
        patients, total = await asyncio.gather(
            query_service.fetch(query),
            query_service.count(query),
        )

        enrichment = await enrichment_service.enrich(patients)

        items = []
        for p in patients:
            pid = str(p.patient_id)
            item = PatientSchema.from_orm(p).model_dump()

            # Add health facility if available
            if p.health_facility:
                item["health_facility"] = HealthFacilitySchema.from_orm(
                    p.health_facility
                ).model_dump()

            # Add care providers if available
            if p.care_providers:
                item["care_providers"] = [
                    CareProviderSchema.from_orm(cp).model_dump()
                    for cp in p.care_providers
                ]

            # Add packages from package_assignments if available
            if p.package_assignments:
                item["packages"] = [
                    PatientPackageAssignmentWithDetailSchema.from_orm(
                        assignment
                    ).model_dump()
                    for assignment in p.package_assignments
                ]

            # Add current package if available
            item["current_package"] = (
                PatientPackageAssignmentWithDetailSchema.from_orm(p.current_package)
                if p.current_package is not None
                else None
            )

            # Add CGM reports from enrichment
            item["reports"] = {"cgm": enrichment["cgm"].get(pid, [])}
            item["last_active_at"] = enrichment["last_active"].get(pid)
            items.append(item)

        return SuccessResponse(
            message="Patients fetched successfully",
            data={
                "total": total,
                "items": items,
            },
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
