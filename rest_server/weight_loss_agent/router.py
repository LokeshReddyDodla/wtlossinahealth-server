from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile, status, HTTPException, Query

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor, get_current_actor
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.patient_access import (
    resolve_patient_access,
    verify_enrollment_access,
    verify_enrollment_access_for_care_provider,
)
from lib.dependencies.service_dependencies import (
    get_agentic_chat_service,
    get_care_provider_access_service,
    get_care_provider_profile_service,
    get_glp1_injection_service,
    get_holistic_summary_service,
    get_plan_composer_service,
    get_task_service,
    get_weight_loss_agent_service,
)
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.services.care_provider_access_service import CareProviderAccessService
from lib.services.care_provider_profile_service import CareProviderProfileService
from lib.schemas.weight_loss_agent import (
    ChatRequest,
    HealthIndicator,
    InbodyReport,
    InbodyReportAnalysisResult,
    InbodyReportCreate,
    InbodyReportDetail,
    InbodyReportUpload,
    WeightLossAgentAnalysisResponse,
    WeightLossEnrollment,
    WeightLossEnrollmentCreate,
    WeightLossEnrollmentUpdate,
    WeightLossProgressReport,
)
from lib.schemas.weightloss_agent.agentic_settings import (
    GlpInjectionSettingsRecord,
    GlpInjectionSettingsUpsert,
)
from lib.services.weight_loss_agent_service import WeightLossAgentService
from lib.services.weightloss_agent.agentic_chat_service import (
    AgenticChatService,
)
from lib.services.weightloss_agent.glp1_injection_service import (
    Glp1InjectionService,
)
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)
from lib.services.weightloss_agent.task_service import TaskService
from lib.utils.care_provider_permissions import (
    CareProviderFeature,
    CareProviderPermissionAction,
)
from lib.utils.http_exceptions import raise_http_exception

from rest_server.response_models import SuccessResponse

# Helper function to parse various date formats
def parse_flexible_date(date_str: str) -> datetime:
    """Parse date string in multiple formats"""
    
    # Remove any trailing 'Z' or timezone info for initial parsing
    clean_date = date_str.replace('Z', '').strip()
    
    # Try different formats
    formats_to_try = [
        '%Y-%m-%d',           # 2024-10-19
        '%Y-%m-%d %H:%M:%S',  # 2024-10-19 14:30:00
        '%Y-%m-%dT%H:%M:%S',  # 2024-10-19T14:30:00
        '%d/%m/%Y',           # 19/10/2024
        '%d_%m_%Y',           # 19_10_2024
        '%d-%m-%Y',           # 19-10-2024
        '%m/%d/%Y',           # 10/19/2024 (US format)
        '%d %b %Y',           # 19 Oct 2024
        '%d %B %Y',           # 19 October 2024
    ]
    
    for fmt in formats_to_try:
        try:
            parsed = datetime.strptime(clean_date, fmt)
            # If no time component, set to start of day
            if 'H' not in fmt and 'M' not in fmt and 'S' not in fmt:
                parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            return parsed
        except ValueError:
            continue
    
    # Try ISO format as last resort
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        pass
    
    raise ValueError(f"Unable to parse date: {date_str}. Supported formats: YYYY-MM-DD, DD/MM/YYYY, DD_MM_YYYY, ISO format")


router = APIRouter(prefix="/weight-loss-agent", tags=["Weight Loss Agent"])


@router.post(
    "/enroll",
    response_model=SuccessResponse[WeightLossEnrollment],
    status_code=status.HTTP_201_CREATED,
    summary="Enroll patient in weight loss program",
    description="Only doctors can enroll patients in the weight loss program",
)
async def enroll_patient(
    enrollment_data: WeightLossEnrollmentCreate,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    care_provider_service: CareProviderProfileService = Depends(
        get_care_provider_profile_service
    ),
    current_care_provider: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
            log_activity=True,
        )
    ),
):
    """Enroll a patient in the weight loss program (doctor only)"""

    try:
        # Verify the care provider is assigned to this patient
        if not await care_provider_service.is_patient_assigned(
            care_provider_id=current_care_provider.care_provider_id,
            patient_id=enrollment_data.patient_id,
        ):
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="You do not have access to this patient",
            )

        enrollment = await weight_loss_service.enroll_patient_in_weight_loss_program(
            enrollment_data
        )

        return SuccessResponse(
            status="success",
            message="Patient enrolled successfully in weight loss program",
            data=enrollment,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.get(
    "/enrollment/{enrollment_id}/analyze",
    response_model=SuccessResponse[WeightLossAgentAnalysisResponse],
    summary="Analyze weight loss progress (GET)",
    description="Generate AI-powered analysis of weight loss progress",
)
async def analyze_weight_loss_progress_get(
    enrollment_id: UUID,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Generate AI analysis of weight loss progress (GET variant)"""

    try:
        await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )

        from datetime import datetime

        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None

        analysis = await weight_loss_service.analyze_weight_loss_progress(enrollment_id, start, end)

        return SuccessResponse(
            status="success",
            message="Analysis generated successfully",
            data=analysis,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.put(
    "/enrollment/{enrollment_id}",
    response_model=SuccessResponse[WeightLossEnrollment],
    summary="Update patient enrollment",
    description="Update weight loss program enrollment details",
)
async def update_enrollment(
    enrollment_id: UUID,
    update_data: WeightLossEnrollmentUpdate,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_care_provider: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.UPDATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
            log_activity=True,
        )
    ),
):
    """Update patient enrollment details"""

    try:
        await verify_enrollment_access_for_care_provider(
            enrollment_id=enrollment_id,
            care_provider=current_care_provider,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )

        enrollment = await weight_loss_service.update_patient_enrollment(enrollment_id, update_data)

        return SuccessResponse(
            status="success",
            message="Enrollment updated successfully",
            data=enrollment,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.get(
    "/patient/{patient_id}/enrollment",
    response_model=SuccessResponse[WeightLossEnrollment],
    summary="Get patient enrollment",
    description="Get patient's current weight loss program enrollment",
)
async def get_patient_enrollment(
    patient_id: UUID,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get patient's weight loss enrollment"""

    try:
        verified_patient_id = await resolve_patient_access(
            actor=actor,
            patient_id=patient_id,
            care_provider_access_service=care_provider_access_service,
        )
        enrollment = await weight_loss_service.get_patient_enrollment_by_patient_id(verified_patient_id)

        if not enrollment:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Patient not enrolled in weight loss program"
            )

        return SuccessResponse(
            status="success",
            message="Enrollment retrieved successfully",
            data=enrollment,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.post(
    "/enrollment/{enrollment_id}/inbody-report",
    response_model=SuccessResponse[InbodyReportAnalysisResult],
    status_code=status.HTTP_201_CREATED,
    summary="Upload, analyze and store inbody report",
    description="Upload an inbody report file (PDF/image), analyze it with AI, and store the results in database. The file content will be processed by AI to extract health metrics and provide personalized insights.",
)
async def upload_and_analyze_inbody_report(
    enrollment_id: UUID,
    report_file: UploadFile = File(...),
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    plan_composer_service: PlanComposerService = Depends(
        get_plan_composer_service
    ),
    current_care_provider: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
            log_activity=True,
        )
    ),
):
    """Upload an inbody report file and get AI analysis"""

    try:
        if not report_file:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Report file is required"
            )

        # Validate file type
        allowed_types = ["image/jpeg", "image/png", "image/jpg", "application/pdf"]
        if report_file.content_type not in allowed_types:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=f"Invalid file type. Allowed types: {', '.join(allowed_types)}"
            )

        # Verify CP has access to this enrollment's patient
        enrollment = await verify_enrollment_access_for_care_provider(
            enrollment_id=enrollment_id,
            care_provider=current_care_provider,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )
        patient_id = enrollment.get("patient_id")

        # Process file and get AI analysis
        analysis_result = await weight_loss_service.process_and_analyze_inbody_report(
            enrollment_id=enrollment_id,
            report_file=report_file,
            user_id=patient_id
        )

        # Trigger plan regeneration when new inbody data arrives
        if patient_id:
            await plan_composer_service.maybe_regenerate_plan(
                UUID(patient_id) if isinstance(patient_id, str) else patient_id,
                force=True,
            )

        # New body-composition data invalidates the whole-person summary.
        from lib.workers.arq.redis import enqueue_job

        await enqueue_job(
            "run_whole_person_summary",
            str(enrollment_id),
            True,
            _job_id=f"holistic-summary-inbody-{enrollment_id}-{datetime.utcnow().date().isoformat()}",
        )

        return SuccessResponse(
            status="success",
            message="Inbody report analyzed and stored successfully. The report has been processed by AI and saved to the database. Note: AI summary will be available after database migration.",
            data=analysis_result,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.get(
    "/enrollment/{enrollment_id}/inbody-report",
    response_model=SuccessResponse[InbodyReportDetail],
    summary="Get latest inbody report",
    description="Retrieve the most recent inbody report for an enrollment, including highlighted measurements like skeletal muscle mass, body fat %, segmental lean analysis, visceral fat level, and basal metabolic rate.",
)
async def get_latest_inbody_report(
    enrollment_id: UUID,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get the most recent inbody report along with highlighted measurements"""

    try:
        await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )

        report_with_details = await weight_loss_service.get_latest_inbody_report_with_details(
            enrollment_id
        )

        if not report_with_details:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Inbody report not found"
            )

        return SuccessResponse(
            status="success",
            message="Inbody report retrieved successfully",
            data=report_with_details,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.post(
    "/enrollment/{enrollment_id}/inbody-report/store",
    response_model=SuccessResponse[InbodyReportAnalysisResult],
    summary="Retry storing inbody report analysis (DEPRECATED)",
    description="This endpoint is deprecated. Reports are now automatically stored when uploaded. Use only for retrying failed storage attempts.",
    deprecated=True,
)
async def store_inbody_report_analysis(
    enrollment_id: UUID,
    analysis_data: InbodyReportAnalysisResult,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    current_care_provider: CareProvider = Depends(
        get_current_care_provider(
            action=CareProviderPermissionAction.CREATE,
            feature=CareProviderFeature.PATIENTS,
            check_permissions=True,
            log_activity=True,
        )
    ),
):
    """Store the analyzed inbody report data in database"""

    try:
        await verify_enrollment_access_for_care_provider(
            enrollment_id=enrollment_id,
            care_provider=current_care_provider,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )
        if not analysis_data:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Analysis data is required"
            )

        # Check if already stored
        if analysis_data.report_id and analysis_data.metadata.get("stored", False):
            return SuccessResponse(
                status="success",
                message="Inbody report analysis is already stored in database",
                data=analysis_data,
            )

        # Get patient_id from enrollment (MongoDB)
        enrollment = await weight_loss_service.get_patient_enrollment(enrollment_id)
        if not enrollment:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Enrollment not found"
            )
        patient_id = enrollment.get("patient_id")

        # Note: This endpoint is deprecated as reports are auto-stored on upload
        # The store_inbody_report_analysis method no longer exists in the service
        raise_http_exception(
            status_code=status.HTTP_410_GONE,
            message="This endpoint is deprecated. Reports are automatically stored when uploaded."
        )

        # return SuccessResponse(
        #     status="success",
        #     message="Inbody report analysis stored successfully",
        #     data={},
        # )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.get(
    "/enrollment/{enrollment_id}/progress",
    response_model=SuccessResponse[WeightLossProgressReport],
    summary="Get weight loss progress",
    description="Get comprehensive weight loss progress report",
)
async def get_weight_loss_progress(
    enrollment_id: UUID,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get weight loss progress report"""

    try:
        await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )

        from datetime import datetime

        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None

        progress_data = await weight_loss_service.get_weight_loss_progress_data(enrollment_id, start, end)

        return SuccessResponse(
            status="success",
            message="Progress report generated successfully",
            data=progress_data,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.post(
    "/enrollment/{enrollment_id}/analyze",
    response_model=SuccessResponse[WeightLossAgentAnalysisResponse],
    summary="Analyze weight loss progress",
    description="Generate AI-powered analysis of weight loss progress",
)
async def analyze_weight_loss_progress(
    enrollment_id: UUID,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Generate AI analysis of weight loss progress"""

    try:
        await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )

        from datetime import datetime

        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None

        analysis = await weight_loss_service.analyze_weight_loss_progress(enrollment_id, start, end)

        return SuccessResponse(
            status="success",
            message="Analysis generated successfully",
            data=analysis,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.get(
    "/enrollment/{enrollment_id}/inbody-reports",
    response_model=SuccessResponse[List[InbodyReport]],
    summary="Get inbody reports",
    description="Get all inbody reports for a patient's enrollment",
)
async def get_inbody_reports(
    enrollment_id: UUID,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get all inbody reports for an enrollment"""

    try:
        # Verify caller owns this enrollment
        await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )
        
        # Get all reports for this enrollment from MongoDB
        reports_cursor = weight_loss_service.reports_collection.find({
            "enrollment_id": str(enrollment_id)
        }).sort("report_date", -1)
        
        reports = await reports_cursor.to_list(length=None)
        
        # Transform reports to match the schema
        from uuid import uuid4
        for report in reports:
            if "_id" in report:
                del report["_id"]
            
            # Add missing fields to measurements
            if "measurements" in report:
                for measurement in report["measurements"]:
                    if "measurement_id" not in measurement:
                        measurement["measurement_id"] = str(uuid4())
                    if "report_id" not in measurement:
                        measurement["report_id"] = report.get("report_id")
                    if "created_at" not in measurement:
                        measurement["created_at"] = report.get("created_at")
            
            # Add missing fields to health_indicators
            if "health_indicators" in report:
                for indicator in report["health_indicators"]:
                    if "indicator_id" not in indicator:
                        indicator["indicator_id"] = str(uuid4())
                    if "report_id" not in indicator:
                        indicator["report_id"] = report.get("report_id")
                    if "created_at" not in indicator:
                        indicator["created_at"] = report.get("created_at")

        return SuccessResponse(
            status="success",
            message="Inbody reports retrieved successfully",
            data=reports,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.get(
    "/enrollment/{enrollment_id}/inbody-report/{report_id}/health-indicators",
    response_model=SuccessResponse[List[HealthIndicator]],
    summary="Get health indicators",
    description="Get health indicators for a specific inbody report",
)
async def get_health_indicators(
    enrollment_id: UUID,
    report_id: UUID,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Get health indicators for an inbody report"""

    try:
        await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )
        # Get report from MongoDB
        report = await weight_loss_service.reports_collection.find_one({
            "report_id": str(report_id)
        })

        if not report:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Inbody report not found"
            )

        # Extract health indicators (embedded in report)
        health_indicators = report.get("health_indicators", [])
        
        # Add missing fields to match schema
        from uuid import uuid4
        for indicator in health_indicators:
            if "indicator_id" not in indicator:
                indicator["indicator_id"] = str(uuid4())
            if "report_id" not in indicator:
                indicator["report_id"] = report.get("report_id")
            if "created_at" not in indicator:
                indicator["created_at"] = report.get("created_at")

        return SuccessResponse(
            status="success",
            message="Health indicators retrieved successfully",
            data=health_indicators,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.post(
    "/enrollment/{enrollment_id}/chat",
    response_model=SuccessResponse[Dict],
    summary="Chat with weight loss agent",
    description="Ask questions about weight loss progress and get AI-powered responses based on reports and data",
)
async def chat_with_weight_loss_agent(
    enrollment_id: UUID,
    chat_request: ChatRequest,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    agentic_chat_service: AgenticChatService = Depends(get_agentic_chat_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Chat with agentic weight loss coach"""

    try:
        user_question = chat_request.question.strip()

        if not user_question:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Question is required"
            )

        # Verify caller owns this enrollment and get enrollment data
        enrollment = await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )
        patient_id = enrollment.get("patient_id")
        patient_uuid = UUID(patient_id)

        # Trigger any due follow-ups/check-ins on this endpoint call so the
        # agentic behavior is visible inside the weightloss chat path.
        await agentic_chat_service.run_scheduled_for_user(patient_uuid)

        await agentic_chat_service.record_user_message(
            patient_uuid, user_question
        )
        agentic_response = await agentic_chat_service.handle_user_message(
            patient_uuid,
            user_question,
            enrollment_id=enrollment_id,
        )
        chat_id = await agentic_chat_service.get_or_create_weightloss_chat_id(
            patient_uuid
        )

        return SuccessResponse(
            status="success",
            message="Message processed",
            data={
                "chat_id": chat_id,
                "status": "queued",
                "agentic_response": agentic_response,
            },
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.get(
    "/enrollment/{enrollment_id}/chat",
    response_model=SuccessResponse[Dict],
    summary="Get weight loss agent chat history",
    description="Fetch previously stored chat messages for the enrollment's Weightloss Coach thread",
)
async def get_weight_loss_agent_chat_history(
    enrollment_id: UUID,
    limit: int = Query(200, ge=1, le=500),
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    agentic_chat_service: AgenticChatService = Depends(get_agentic_chat_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    try:
        # Verify caller owns this enrollment and get enrollment data
        enrollment = await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )
        patient_id = enrollment.get("patient_id")
        history = await agentic_chat_service.get_chat_history(
            UUID(patient_id), limit=limit
        )
        return SuccessResponse(
            status="success",
            message="Chat history retrieved successfully",
            data=history,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


# ── Task Endpoints ───────────────────────────────────────────────────────────


@router.get(
    "/enrollment/{enrollment_id}/tasks/today",
    response_model=SuccessResponse[Dict],
    summary="Get today's tasks",
    description="Return all tasks for the enrolled patient for today, regardless of status.",
)
async def get_today_tasks(
    enrollment_id: UUID,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    task_service: TaskService = Depends(get_task_service),
    injection_service: Glp1InjectionService = Depends(get_glp1_injection_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    try:
        enrollment = await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )
        patient_id = enrollment.get("patient_id")

        # Use patient's configured timezone so "today" matches the date used
        # when tasks are created during the daily checkin tick.
        from datetime import timezone as _tz
        from zoneinfo import ZoneInfo

        settings = await injection_service.get_settings(UUID(patient_id))
        tz_name = (settings or {}).get("timezone") or "Asia/Kolkata"
        now_local = datetime.now(_tz.utc).astimezone(ZoneInfo(tz_name))
        today_str = now_local.date().isoformat()

        tasks = await task_service.get_tasks_for_date(UUID(patient_id), today_str)

        # Strip MongoDB _id for JSON serialisation
        sanitised = []
        for task in tasks:
            t = {k: v for k, v in task.items() if k != "_id"}
            # Ensure datetimes are ISO strings
            for dt_field in ("created_at", "updated_at", "completed_at"):
                if isinstance(t.get(dt_field), datetime):
                    t[dt_field] = t[dt_field].isoformat()
            sanitised.append(t)

        return SuccessResponse(
            status="success",
            message="Today's tasks retrieved",
            data={"date": today_str, "tasks": sanitised},
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.patch(
    "/enrollment/{enrollment_id}/tasks/{task_id}/complete",
    response_model=SuccessResponse[Dict],
    summary="Mark a task as completed",
    description="Mark a specific task as done (manually completed by patient).",
)
async def complete_task(
    enrollment_id: UUID,
    task_id: str,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    task_service: TaskService = Depends(get_task_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    try:
        enrollment = await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )
        patient_id = enrollment.get("patient_id")

        task = await task_service.get_task_by_id(task_id)
        if not task:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Task not found",
            )
        if task.get("user_id") != str(patient_id):
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Task does not belong to this enrollment",
            )
        if task.get("status") == "done":
            return SuccessResponse(
                status="success",
                message="Task already completed",
                data={"task_id": task_id, "status": "done"},
            )

        await task_service.mark_task_done(task_id, source="manual")

        return SuccessResponse(
            status="success",
            message="Task marked as completed",
            data={"task_id": task_id, "status": "done"},
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.post(
    "/glp-injection",
    response_model=SuccessResponse[GlpInjectionSettingsRecord],
    status_code=status.HTTP_200_OK,
    summary="Upsert GLP-1 injection settings",
)
async def upsert_glp_injection_settings(
    payload: GlpInjectionSettingsUpsert,
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.CREATE,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
    injection_service: Glp1InjectionService = Depends(
        get_glp1_injection_service
    ),
    agentic_chat_service: AgenticChatService = Depends(
        get_agentic_chat_service
    ),
    plan_composer_service: PlanComposerService = Depends(
        get_plan_composer_service
    ),
):
    try:
        patient_id = await resolve_patient_access(
            actor=actor,
            patient_id=payload.user_id,
            care_provider_access_service=care_provider_access_service,
        )
        payload.user_id = patient_id
        record = await injection_service.upsert_settings(payload)
        await agentic_chat_service.initialize_symptom_flow(payload.user_id)
        # Trigger plan regeneration when injection settings change
        await plan_composer_service.maybe_regenerate_plan(
            payload.user_id, force=True
        )
        return SuccessResponse(
            status="success",
            message="GLP-1 injection settings updated",
            data=record,
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST, message=str(e)
        )


@router.get(
    "/enrollment/{enrollment_id}/daily-analysis",
    response_model=SuccessResponse[Dict],
    summary="Get the holistic daily coach analysis for a date",
    description=(
        "Returns the stored whole-day analysis (diet, activity, glucose and "
        "medication verdicts plus the coach message) for the given date. "
        "Defaults to yesterday in the patient's timezone. Pass generate=true "
        "to build it on demand when it does not exist yet."
    ),
)
async def get_daily_coach_analysis(
    enrollment_id: UUID,
    date: Optional[str] = Query(
        None, description="ISO date (patient-local day); defaults to yesterday"
    ),
    generate: bool = Query(
        False, description="Generate the analysis now if it is missing"
    ),
    weight_loss_service: WeightLossAgentService = Depends(
        get_weight_loss_agent_service
    ),
    holistic_summary_service=Depends(get_holistic_summary_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Fetch (or generate) the stored DailyCoachAnalysis for one day."""

    try:
        enrollment = await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )

        raw_patient_id = enrollment.get("patient_id")
        patient_id = (
            UUID(raw_patient_id)
            if isinstance(raw_patient_id, str)
            else raw_patient_id
        )

        if date:
            target_date = parse_flexible_date(date).date()
        else:
            from zoneinfo import ZoneInfo

            from datetime import timedelta

            timezone_name = (
                await holistic_summary_service.holistic_data_service.get_patient_timezone(
                    patient_id
                )
            )
            target_date = (
                datetime.now(ZoneInfo(timezone_name)).date() - timedelta(days=1)
            )

        analysis = await holistic_summary_service.get_daily_analysis(
            patient_id, target_date
        )

        if (
            generate
            and (not analysis or analysis.get("status") != "complete")
        ):
            analysis = await holistic_summary_service.generate_daily_coach_analysis(
                patient_id, target_date
            )

        if not analysis:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message=(
                    f"No daily analysis found for {target_date.isoformat()}. "
                    "Pass generate=true to build one now."
                ),
            )

        return SuccessResponse(
            status="success",
            message="Daily coach analysis retrieved successfully",
            data=analysis,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST, message=str(e)
        )


@router.get(
    "/enrollment/{enrollment_id}/whole-person-summary",
    response_model=SuccessResponse[Dict],
    summary="Get the whole-person summary",
    description=(
        "Returns the latest big-picture summary of the patient (body status, "
        "progress, eating/activity/glucose patterns, medication context, "
        "risks and priorities). Pass refresh=true to regenerate it now."
    ),
)
async def get_whole_person_summary(
    enrollment_id: UUID,
    refresh: bool = Query(False, description="Force regeneration now"),
    weight_loss_service: WeightLossAgentService = Depends(
        get_weight_loss_agent_service
    ),
    holistic_summary_service=Depends(get_holistic_summary_service),
    actor: Actor = Depends(
        get_current_actor(
            allowed_roles=[ProfileTypeEnum.PATIENT, ProfileTypeEnum.CARE_PROVIDER],
            care_provider_feature=CareProviderFeature.PATIENTS,
            care_provider_action=CareProviderPermissionAction.READ,
        )
    ),
    care_provider_access_service: CareProviderAccessService = Depends(
        get_care_provider_access_service
    ),
):
    """Fetch (or regenerate) the WholePersonSummary for an enrollment."""

    try:
        await verify_enrollment_access(
            enrollment_id=enrollment_id,
            actor=actor,
            weight_loss_service=weight_loss_service,
            care_provider_access_service=care_provider_access_service,
        )

        if refresh:
            summary = await holistic_summary_service.generate_whole_person_summary(
                enrollment_id, force=True
            )
        else:
            summary = await holistic_summary_service.get_whole_person_summary(
                enrollment_id
            )
            if not summary:
                summary = (
                    await holistic_summary_service.generate_whole_person_summary(
                        enrollment_id
                    )
                )

        return SuccessResponse(
            status="success",
            message="Whole-person summary retrieved successfully",
            data=summary,
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_400_BAD_REQUEST, message=str(e)
        )
