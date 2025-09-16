from typing import Dict, List, Optional
from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.service_dependencies import get_weight_loss_agent_service
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.schemas.weight_loss_agent import (
    HealthIndicator,
    InbodyReport,
    InbodyReportAnalysisResult,
    InbodyReportCreate,
    InbodyReportUpload,
    WeightLossAgentAnalysisResponse,
    WeightLossEnrollment,
    WeightLossEnrollmentCreate,
    WeightLossEnrollmentUpdate,
    WeightLossProgressReport,
)
from lib.services.weight_loss_agent_service import WeightLossAgentService
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
    
    # TODO: Uncomment for production - care provider auth required
    #  current_care_provider: CareProvider = Depends(
    #      get_current_care_provider(
    #          action=CareProviderPermissionAction.CREATE,
    #          feature=CareProviderFeature.PATIENTS,
    #          check_permissions=True,
    #          log_activity=True,
    #      )
    #  ),
):
    """Enroll a patient in the weight loss program (doctor only)"""

    try:
        enrollment = await weight_loss_service.enroll_patient_in_weight_loss_program(
            enrollment_data
        )

        return SuccessResponse(
            status="success",
            message="Patient enrolled successfully in weight loss program",
            data=enrollment,
        )
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
    current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Update patient enrollment details"""

    try:
        enrollment = await weight_loss_service.update_patient_enrollment(enrollment_id, update_data)

        return SuccessResponse(
            status="success",
            message="Enrollment updated successfully",
            data=enrollment,
        )
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
    current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Get patient's weight loss enrollment"""

    try:
        enrollment = await weight_loss_service.get_patient_enrollment(patient_id)

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
    # TODO: Uncomment for production - care provider auth required
    # current_care_provider: CareProvider = Depends(get_current_care_provider),
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

        # Process file and get AI analysis
        analysis_result = await weight_loss_service.process_and_analyze_inbody_report(
            enrollment_id=enrollment_id,
            report_file=report_file,
            user_id="test-user"  # TODO: Use current_care_provider.care_provider_id for production
        )

        return SuccessResponse(
            status="success",
            message="Inbody report analyzed and stored successfully. The report has been processed by AI and saved to the database. Note: AI summary will be available after database migration.",
            data=analysis_result,
        )
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
    # TODO: Uncomment for production - care provider auth required
    # current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Store the analyzed inbody report data in database"""

    try:
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

        # Store the analysis results in database (retry if failed before)
        stored_result = await weight_loss_service.store_inbody_report_analysis(
            enrollment_id=enrollment_id,
            analysis_result=analysis_data,
            user_id="test-user"  # TODO: Use current_care_provider.care_provider_id for production
        )

        return SuccessResponse(
            status="success",
            message="Inbody report analysis stored successfully",
            data=stored_result,
        )
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
    # TODO: Uncomment for production - care provider auth required
    # current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Get weight loss progress report"""

    try:
        from datetime import datetime

        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None

        progress_data = await weight_loss_service.get_weight_loss_progress_data(enrollment_id, start, end)

        return SuccessResponse(
            status="success",
            message="Progress report generated successfully",
            data=progress_data,
        )
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
    # TODO: Uncomment for production - care provider auth required
    # current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Generate AI analysis of weight loss progress"""

    try:
        from datetime import datetime

        start = datetime.fromisoformat(start_date) if start_date else None
        end = datetime.fromisoformat(end_date) if end_date else None

        analysis = await weight_loss_service.analyze_weight_loss_progress(enrollment_id, start, end)

        return SuccessResponse(
            status="success",
            message="Analysis generated successfully",
            data=analysis,
        )
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.post(
    "/enrollment/{enrollment_id}/inbody-report/{report_id}/process",
    response_model=SuccessResponse[dict],
    summary="Process inbody report",
    description="Process uploaded inbody report image and extract measurements",
)
async def process_inbody_report(
    enrollment_id: UUID,
    report_id: UUID,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Process inbody report and extract measurements using AI"""

    try:
        # Get the report to access the image URL
        async with weight_loss_service.postgres_store.get_session() as session:
            from lib.models.weight_loss_agent import InbodyReport
            report = await session.get(InbodyReport, report_id)
            if not report:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Inbody report not found"
                )

            # Get patient information
            from lib.models.weight_loss_agent import WeightLossAgentEnrollment
            enrollment = await session.get(WeightLossAgentEnrollment, enrollment_id)
            if not enrollment:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found"
                )

            patient = enrollment.patient

        # Process the image to extract measurements
        from lib.services.inbody_image_processing_service import InbodyImageProcessingService
        from lib.services.health_indicator_analysis_service import HealthIndicatorAnalysisService

        image_processor = InbodyImageProcessingService()
        health_analyzer = HealthIndicatorAnalysisService(weight_loss_service.postgres_store)

        measurements_data, confidence_score = await image_processor.process_inbody_image(
            str(report.image_url)  # Convert Column to string
        )

        if not measurements_data:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Unable to extract measurements from image. Please ensure the image is clear and contains valid inbody report data."
            )

        # Process measurements and create health indicators
        processed_measurements, health_indicators = await weight_loss_service.process_inbody_image(
            report_id, measurements_data
        )

        # Analyze health indicators with AI
        if processed_measurements:
            ai_health_indicators = await health_analyzer.analyze_health_indicators(
                processed_measurements, patient
            )
            # Add AI-generated indicators to the list
            health_indicators.extend(ai_health_indicators)

        return SuccessResponse(
            status="success",
            message="Inbody report processed successfully",
            data={
                "measurements_processed": len(processed_measurements),
                "health_indicators_found": len(health_indicators),
                "extraction_confidence": confidence_score,
                "abnormal_indicators": [
                    {
                        "name": indicator.indicator_name,
                        "value": indicator.value,
                        "unit": indicator.unit,
                        "type": indicator.indicator_type,
                        "level": indicator.abnormality_level,
                        "explanation": indicator.analysis_explanation,
                    }
                    for indicator in health_indicators
                    if indicator.is_abnormal  # type: ignore
                ],
                "normal_indicators": [
                    {
                        "name": indicator.indicator_name,
                        "value": indicator.value,
                        "unit": indicator.unit,
                    }
                    for indicator in health_indicators
                    if not indicator.is_abnormal  # type: ignore
                ],
            },
        )
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, message=f"Error processing inbody report: {str(e)}")


@router.get(
    "/enrollment/{enrollment_id}/inbody-reports",
    response_model=SuccessResponse[List[InbodyReport]],
    summary="Get inbody reports",
    description="Get all inbody reports for a patient's enrollment",
)
async def get_inbody_reports(
    enrollment_id: UUID,
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    # TODO: Uncomment for production - care provider auth required
    # current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Get all inbody reports for an enrollment"""

    try:
        from sqlalchemy.orm import selectinload

        async with weight_loss_service.postgres_store.get_session() as session:
            from lib.models.weight_loss_agent import WeightLossAgentEnrollment
            enrollment = await session.get(
                WeightLossAgentEnrollment,
                enrollment_id,
                options=[
                    selectinload(WeightLossAgentEnrollment.inbody_reports),
                ]
            )

            if not enrollment:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found"
                )

            return SuccessResponse(
                status="success",
                message="Inbody reports retrieved successfully",
                data=enrollment.inbody_reports,
            )
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
    # TODO: Uncomment for production - care provider auth required
    # current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Get health indicators for an inbody report"""

    try:
        from sqlalchemy.orm import selectinload

        async with weight_loss_service.postgres_store.get_session() as session:
            from lib.models.weight_loss_agent import InbodyReport
            report = await session.get(
                InbodyReport,
                report_id,
                options=[selectinload(InbodyReport.health_indicators)]
            )

            if not report:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Inbody report not found"
                )

            return SuccessResponse(
                status="success",
                message="Health indicators retrieved successfully",
                data=report.health_indicators,
            )
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))


@router.post(
    "/enrollment/{enrollment_id}/chat",
    response_model=SuccessResponse[Dict],
    summary="Chat with weight loss agent",
    description="""Chat with AI weight loss agent about progress, diet, fitness, and health metrics.

    The chatbot has access to:
    - Inbody report summaries and health indicators
    - Daily meal data and calorie tracking
    - Fitness activity data (steps, energy expenditure, workouts)
    - Vital signs (weight, blood pressure)
    - Progress tracking and goal analysis

    Supports queries about:
    - Weight loss progress and trends
    - Dietary advice and meal planning
    - Exercise recommendations
    - Health metric interpretation
    - Goal setting and achievement strategies
    """,
)
async def chat_with_weight_loss_agent(
    enrollment_id: UUID,
    chat_request: Dict[str, str],
    weight_loss_service: WeightLossAgentService = Depends(get_weight_loss_agent_service),
    # TODO: Uncomment for production - care provider auth required
    # current_care_provider: CareProvider = Depends(get_current_care_provider),
):
    """Chat with AI weight loss agent about progress and reports"""

    try:
        user_question = chat_request.get("question", "").strip()
        conversation_id = chat_request.get("conversation_id", f"chat_{enrollment_id}_{datetime.now().isoformat()}")

        if not user_question:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Question is required"
            )

        # Use the agentic flow by default to orchestrate intent analysis
        response = await weight_loss_service.agentic_weight_loss_coach(
            enrollment_id=enrollment_id,
            user_input=user_question,
            user_id="test-user",  # TODO: Use current_care_provider.care_provider_id for production
            conversation_id=conversation_id,
        )

        return SuccessResponse(
            status="success",
            message="AI response generated successfully",
            data=response,
        )
    except Exception as e:
        raise_http_exception(status_code=status.HTTP_400_BAD_REQUEST, message=str(e))
