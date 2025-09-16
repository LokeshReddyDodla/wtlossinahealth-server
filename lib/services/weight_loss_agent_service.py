import asyncio
import re
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, desc, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload, selectinload

from lib.core.constants import ProfileTypeEnum
from lib.core.postgres_store import PostgresStore
from lib.models.care_provider import CareProvider
from lib.models.patient import Patient
from lib.models.patient_meal import PatientMeal
from lib.models.patient_vital import PatientVital
from lib.models.weight_loss_agent import (
    HealthIndicator,
    InbodyMeasurement,
    InbodyReport,
    WeightLossAgentEnrollment,
)
from lib.schemas.weight_loss_agent import (
    InbodyReportAnalysisResult,
    InbodyReportCreate,
    WeightLossEnrollmentCreate,
    WeightLossEnrollmentUpdate,
)
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.s3_utils import upload_file_to_s3


class WeightLossAgentService:
    """Agentic service for managing weight loss agent functionality with single API orchestration"""

    def __init__(self, postgres_store: PostgresStore):
        self.postgres_store = postgres_store
        self.agent_memory = {}  # In-memory conversation state (use Redis in production)

    async def enroll_patient_in_weight_loss_program(
        self,
        enrollment_data: WeightLossEnrollmentCreate,
    ) -> WeightLossAgentEnrollment:
        """Enroll a patient in the weight loss program (doctor only)"""

        async with self.postgres_store.get_session() as session:
            # Verify the care provider is a doctor
            care_provider = await session.get(CareProvider, enrollment_data.enrolled_by_care_provider_id)
            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Care provider not found"
                )

            if str(care_provider.role).lower() != "doctor":
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="Only doctors can enroll patients in weight loss program"
                )

            # Check if patient already has an active enrollment
            existing_enrollment = await session.execute(
                select(WeightLossAgentEnrollment).where(
                    and_(
                        WeightLossAgentEnrollment.patient_id == enrollment_data.patient_id,
                        WeightLossAgentEnrollment.is_active == True,
                    )
                )
            )
            existing_enrollment = existing_enrollment.scalar_one_or_none()

            if existing_enrollment:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Patient is already enrolled in weight loss program"
                )

            # Verify patient exists
            patient = await session.get(Patient, enrollment_data.patient_id)
            if not patient:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Patient not found"
                )

            # Create enrollment
            enrollment = WeightLossAgentEnrollment(
                patient_id=enrollment_data.patient_id,
                enrolled_by_care_provider_id=enrollment_data.enrolled_by_care_provider_id,
                program_goals=enrollment_data.program_goals,
                target_weight_kg=enrollment_data.target_weight_kg,
                target_bmi=enrollment_data.target_bmi,
            )

            session.add(enrollment)
            await session.commit()
            await session.refresh(enrollment)

            return enrollment

    async def update_patient_enrollment(
        self,
        enrollment_id: UUID,
        update_data: WeightLossEnrollmentUpdate,
    ) -> WeightLossAgentEnrollment:
        """Update patient enrollment details"""

        async with self.postgres_store.get_session() as session:
            enrollment = await session.get(WeightLossAgentEnrollment, enrollment_id)
            if not enrollment:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found"
                )

            # Update fields
            for field, value in update_data.dict(exclude_unset=True).items():
                if hasattr(enrollment, field):
                    setattr(enrollment, field, value)

            await session.commit()
            await session.refresh(enrollment)

            return enrollment

    async def get_patient_enrollment(self, patient_id: UUID) -> Optional[WeightLossAgentEnrollment]:
        """Get patient's weight loss enrollment"""

        async with self.postgres_store.get_session() as session:
            result = await session.execute(
                select(WeightLossAgentEnrollment).where(
                    and_(
                        WeightLossAgentEnrollment.patient_id == patient_id,
                        WeightLossAgentEnrollment.is_active == True,
                    )
                ).options(
                    selectinload(WeightLossAgentEnrollment.inbody_reports)
                )
            )
            return result.scalar_one_or_none()

    async def create_inbody_report(
        self,
        enrollment_id: UUID,
        report_data: InbodyReportCreate,
    ) -> InbodyReport:
        """Create a new inbody report"""

        async with self.postgres_store.get_session() as session:
            # Verify enrollment exists and is active
            enrollment = await session.get(WeightLossAgentEnrollment, enrollment_id)
            if not enrollment or not enrollment.is_active:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Active enrollment not found"
                )

            # Create inbody report
            report = InbodyReport(
                enrollment_id=enrollment_id,
                ai_summary=report_data.ai_summary,
                original_filename=report_data.original_filename,
                file_size=report_data.file_size,
                content_type=report_data.content_type,
                report_date=report_data.report_date,
            )

            session.add(report)
            await session.commit()
            await session.refresh(report)

            return report

    async def process_inbody_image(
        self,
        report_id: UUID,
        extracted_measurements: List[Dict],
    ) -> Tuple[List[InbodyMeasurement], List[HealthIndicator]]:
        """Process extracted measurements from inbody image"""

        async with self.postgres_store.get_session() as session:
            # Get the report
            report = await session.get(InbodyReport, report_id)
            if not report:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Inbody report not found"
                )

            measurements = []
            health_indicators = []

            # Process each measurement
            for measurement_data in extracted_measurements:
                measurement_type = measurement_data["type"]
                value = measurement_data["value"]
                unit = measurement_data["unit"]
                normal_min = measurement_data.get("normal_min")
                normal_max = measurement_data.get("normal_max")

                # Create measurement
                measurement = InbodyMeasurement(
                    report_id=report_id,
                    measurement_type=measurement_type,
                    value=value,
                    unit=unit,
                    normal_min=normal_min,
                    normal_max=normal_max,
                )
                measurements.append(measurement)
                session.add(measurement)

                # Create health indicator if abnormal
                if normal_min is not None and normal_max is not None and self._is_value_abnormal(value, normal_min, normal_max):
                    indicator = self._create_health_indicator(
                        report_id, measurement_type, value, unit, normal_min, normal_max
                    )
                    health_indicators.append(indicator)
                    session.add(indicator)

            # Mark report as processed
            report.processed = True
            report.extracted_at = datetime.now().replace(tzinfo=None)

            await session.commit()

            # Refresh objects
            for measurement in measurements:
                await session.refresh(measurement)
            for indicator in health_indicators:
                await session.refresh(indicator)

            return measurements, health_indicators

    async def get_daily_reports_data(
        self,
        patient_id: UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Dict]:
        """Get daily meal and fitness reports for a patient"""

        async with self.postgres_store.get_session() as session:
            daily_data = []

            # Get date range
            current_date = start_date.date()
            end_date_only = end_date.date()

            while current_date <= end_date_only:
                date_str = current_date.isoformat()

                # Get meals for the day
                meals_result = await session.execute(
                    select(PatientMeal).where(
                        and_(
                            PatientMeal.patient_id == patient_id,
                            func.date(PatientMeal.date) == current_date,
                        )
                    )
                )
                meals = meals_result.scalars().all()

                # Get vitals for the day
                vitals_result = await session.execute(
                    select(PatientVital).where(
                        and_(
                            PatientVital.patient_id == patient_id,
                            func.date(PatientVital.test_time) == current_date,
                        )
                    )
                )
                vitals = vitals_result.scalars().all()

                # Get fitness data from external service (placeholder)
                fitness_data = await self._get_fitness_data_for_date(
                    patient_id, current_date
                )

                daily_data.append({
                    "date": date_str,
                    "meal_data": {
                        "meals_count": len(meals),
                        "total_calories": sum(
                            meal.total_macro_nutritional_value.calories 
                            for meal in meals 
                            if meal.total_macro_nutritional_value and hasattr(meal.total_macro_nutritional_value, 'calories')
                        ),
                        "meals": [
                            {
                                "meal_id": str(meal.id),
                                "type": meal.type,
                                "calories": meal.total_macro_nutritional_value.calories
                                if meal.total_macro_nutritional_value else 0,
                            }
                            for meal in meals
                        ],
                    } if meals else None,
                    "fitness_data": fitness_data,
                    "vitals_data": {
                        "weight": vitals[-1].weight if vitals and len(vitals) > 0 and vitals[-1].weight else None,
                        "blood_pressure": {
                            "systolic": vitals[-1].systolic_bp if vitals and vitals[-1].systolic_bp else None,
                            "diastolic": vitals[-1].diastolic_bp if vitals and vitals[-1].diastolic_bp else None,
                        } if vitals else None,
                    } if vitals else None,
                })

                current_date += timedelta(days=1)

            return daily_data

    def _classify_query_type(self, question: str) -> str:
        """Classify the type of user query for better context handling"""

        question_lower = question.lower()

        # Progress-related queries
        if any(word in question_lower for word in ["progress", "improvement", "change", "trends", "results"]):
            return "progress_analysis"

        # Diet/meal-related queries
        if any(word in question_lower for word in ["eat", "food", "meal", "diet", "calories", "nutrition", "hungry"]):
            return "diet_advice"

        # Exercise/fitness-related queries
        if any(word in question_lower for word in ["exercise", "workout", "fitness", "run", "walk", "gym", "active"]):
            return "fitness_advice"

        # Health metrics queries
        if any(word in question_lower for word in ["weight", "bmi", "body fat", "muscle", "measurement", "vitals"]):
            return "health_metrics"

        # Goal-related queries
        if any(word in question_lower for word in ["goal", "target", "achieve", "lose weight", "gain muscle"]):
            return "goal_setting"

        # General advice queries
        if any(word in question_lower for word in ["help", "advice", "recommend", "suggest", "how to", "what should"]):
            return "general_advice"

        # Default classification
        return "general_conversation"

    def _generate_contextual_fallback(self, question: str, context_data: Dict, enrollment, daily_reports: List, latest_report) -> str:
        """Generate contextual information for fallback AI responses"""

        context_parts = []

        # Add enrollment context
        if enrollment:
            context_parts.append(f"Patient enrolled in weight loss program for {(datetime.now() - enrollment.enrollment_date).days} days")
            context_parts.append(f"Target weight: {enrollment.target_weight_kg}kg, Target BMI: {enrollment.target_bmi}")
            if enrollment.program_goals:
                context_parts.append(f"Program goals: {enrollment.program_goals}")

        # Add recent activity context
        if daily_reports:
            recent_meals = len([d for d in daily_reports[-7:] if d.get("meal_data")])
            recent_fitness = len([d for d in daily_reports[-7:] if d.get("fitness_data")])
            context_parts.append(f"Recent activity: {recent_meals} days with meal data, {recent_fitness} days with fitness data in last 7 days")

        # Add inbody report context
        if latest_report:
            context_parts.append(f"Latest inbody report from {latest_report.report_date.strftime('%Y-%m-%d')}")
            if hasattr(latest_report, 'measurements') and latest_report.measurements:
                weight_meas = next((m for m in latest_report.measurements if m.measurement_type.lower() == 'weight'), None)
                if weight_meas:
                    context_parts.append(f"Current weight: {weight_meas.value} {weight_meas.unit}")

        # Add question context
        query_type = self._classify_query_type(question)
        context_parts.append(f"Question type: {query_type}")
        context_parts.append(f"User question: {question}")

        return " | ".join(context_parts)

    def _generate_basic_fallback_response(self, question: str, context_data: Dict) -> str:
        """Generate a basic fallback response when AI services are unavailable"""

        query_type = context_data.get("conversation_context", {}).get("query_type", "general")

        base_responses = {
            "progress_analysis": "I'd be happy to help you track your weight loss progress! Based on your recent activity data, I can see you're actively working on your health goals. Keep up the great work with your daily meals and fitness activities.",
            "diet_advice": "Nutrition is key to successful weight loss! I recommend focusing on balanced meals with plenty of vegetables, lean proteins, and whole grains. Try to maintain a moderate calorie deficit while ensuring you get all essential nutrients.",
            "fitness_advice": "Regular exercise is crucial for weight management! Aim for a mix of cardio and strength training. Even moderate daily activity like walking can make a significant difference in your progress.",
            "health_metrics": "Your health metrics are important indicators of progress! Regular monitoring through inbody reports helps track changes in body composition, muscle mass, and overall health status.",
            "goal_setting": "Setting realistic goals is essential for long-term success! Focus on sustainable changes rather than rapid weight loss. Small, consistent improvements add up over time.",
            "general_advice": "I'm here to support your weight loss journey! Remember that sustainable weight loss involves balanced nutrition, regular physical activity, and consistent healthy habits."
        }

        response = base_responses.get(query_type, base_responses["general_advice"])

        # Add personalized touch if we have enrollment data
        enrollment_info = context_data.get("enrollment_info", {})
        if enrollment_info.get("days_enrolled"):
            response += f" You've been on this journey for {enrollment_info['days_enrolled']} days - that's commendable!"

        return response

    async def analyze_weight_loss_progress(
        self,
        enrollment_id: UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        """Analyze weight loss progress using AI"""

        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        async with self.postgres_store.get_session() as session:
            # Get enrollment with patient info
            enrollment = await session.get(
                WeightLossAgentEnrollment,
                enrollment_id,
                options=[
                    joinedload(WeightLossAgentEnrollment.patient),
                    joinedload(WeightLossAgentEnrollment.inbody_reports).joinedload(InbodyReport.measurements),
                    joinedload(WeightLossAgentEnrollment.inbody_reports).joinedload(InbodyReport.health_indicators),
                ]
            )

            if not enrollment:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found"
                )

            # Get daily reports data
            daily_reports = await self.get_daily_reports_data(
                UUID(str(enrollment.patient_id)), start_date, end_date
            )

            # Get latest inbody report
            latest_report = None
            if enrollment.inbody_reports:
                latest_report = max(enrollment.inbody_reports, key=lambda r: r.report_date)

            # Create latest report summary
            latest_report_summary = None
            if latest_report:
                latest_report_summary = {
                    "report_id": str(latest_report.report_id),
                    "report_date": latest_report.report_date.isoformat(),
                    "processed": latest_report.processed,
                    "extraction_confidence": latest_report.extraction_confidence,
                    "abnormal_indicators_count": len([
                        h for h in latest_report.health_indicators if h.is_abnormal
                    ]),
                    "measurements_count": len(latest_report.measurements),
                }

            # Use AI to analyze the data
            ai_service = AiConversationService(
                conversation_type="weight-loss-agent",
                ai_model_provider="openai",  # Can be configured
                selected_ai_model="gpt-4o"
            )
            
            analysis_prompt = self._build_analysis_prompt(
                enrollment, daily_reports, latest_report
            )
            
            # Generate AI analysis
            ai_response = await ai_service.generate_response(
                patient_id=str(enrollment.patient_id),
                user_id=str(enrollment.enrolled_by_care_provider_id),  # Use care provider as user
                conversation_id=f"analysis_{enrollment_id}_{start_date.isoformat()}_{end_date.isoformat()}",
                human_input=analysis_prompt,
                conversation_type="weight-loss-agent",
                additional_context={
                    "analysis_type": "weight_loss_progress",
                    "enrollment_data": {
                        "target_weight": enrollment.target_weight_kg,
                        "target_bmi": enrollment.target_bmi,
                        "program_goals": enrollment.program_goals,
                        "enrollment_date": enrollment.enrollment_date.isoformat(),
                    },
                    "daily_reports": daily_reports,
                    "latest_inbody_report": latest_report_summary if latest_report else None,
                }
            )
            
            # Parse the AI response
            analysis = {
                "enrollment_id": str(enrollment_id),
                "analysis_period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
                "ai_analysis": ai_response.get("response", "Analysis not available"),
                "confidence_score": ai_response.get("metadata", {}).get("confidence_score"),
                "tags": ai_response.get("metadata", {}).get("tags", []),
                "citations": ai_response.get("metadata", {}).get("citations", []),
                "follow_up_questions": ai_response.get("follow_up_questions", []),
            }

            return analysis

    async def get_weight_loss_progress_data(
        self,
        enrollment_id: UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        """Get comprehensive weight loss progress data"""

        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        async with self.postgres_store.get_session() as session:
            # Get enrollment with related data
            enrollment = await session.get(
                WeightLossAgentEnrollment,
                enrollment_id,
                options=[
                    joinedload(WeightLossAgentEnrollment.patient),
                    joinedload(WeightLossAgentEnrollment.inbody_reports).joinedload(InbodyReport.measurements),
                    joinedload(WeightLossAgentEnrollment.inbody_reports).joinedload(InbodyReport.health_indicators),
                ]
            )

            if not enrollment:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found"
                )

            # Get daily reports
            daily_reports = await self.get_daily_reports_data(
                enrollment.patient_id, start_date, end_date
            )

            # Get latest inbody report summary
            latest_report = None
            if enrollment.inbody_reports:
                latest_report = max(enrollment.inbody_reports, key=lambda r: r.report_date)

            latest_report_summary = None
            if latest_report:
                latest_report_summary = {
                    "report_id": str(latest_report.report_id),
                    "report_date": latest_report.report_date.isoformat(),
                    "processed": latest_report.processed,
                    "extraction_confidence": latest_report.extraction_confidence,
                    "abnormal_indicators_count": len([
                        h for h in latest_report.health_indicators if h.is_abnormal
                    ]),
                    "measurements_count": len(latest_report.measurements),
                }

            return {
                "enrollment_id": str(enrollment_id),
                "patient_id": str(enrollment.patient_id),
                "patient_name": f"{enrollment.patient.first_name} {enrollment.patient.last_name}",
                "enrollment_date": enrollment.enrollment_date.isoformat(),
                "is_active": enrollment.is_active,
                "target_weight_kg": enrollment.target_weight_kg,
                "target_bmi": enrollment.target_bmi,
                "latest_inbody_report": latest_report_summary,
                "daily_reports": daily_reports,
                "program_goals": enrollment.program_goals,
            }

    

    def _is_value_abnormal(self, value: float, normal_min: float, normal_max: float) -> bool:
        """Check if a value is outside normal range"""

        return value < normal_min or value > normal_max

    def _create_health_indicator(
        self,
        report_id: UUID,
        indicator_name: str,
        value: float,
        unit: str,
        normal_min: float,
        normal_max: float,
    ) -> HealthIndicator:
        """Create a health indicator for abnormal values"""

        abnormality_level = "high" if value > normal_max else "low"

        return HealthIndicator(
            report_id=report_id,
            indicator_name=indicator_name,
            indicator_type="warning",
            value=value,
            unit=unit,
            is_abnormal=True,
            abnormality_level=abnormality_level,
            normal_range_min=normal_min,
            normal_range_max=normal_max,
            analysis_explanation=f"{indicator_name} is {abnormality_level} compared to normal range",
        )

    async def _get_fitness_data_for_date(self, patient_id: UUID, date: date) -> Optional[Dict]:
        """Get real fitness data for a specific date from FitnessReportService"""

        try:
            # Import the fitness report service
            from lib.dependencies.service_dependencies import get_fitness_report_service

            # Get the fitness report service
            fitness_service = get_fitness_report_service()

            # Fetch the daily fitness report for the specific date
            report = await fitness_service.fetch_daily_report(
                patient_id=str(patient_id),
                date=date,
                regenerate=False  # Don't regenerate if not found
            )

            if report:
                # Extract the relevant fitness metrics from the report
                fitness_stats = report.get("fitness_stats", {})

                return {
                    "steps": fitness_stats.get("steps", 0),
                    "active_energy": fitness_stats.get("active_energy", 0.0),
                    "active_duration": fitness_stats.get("active_duration", 0),
                    "workouts_count": len(report.get("workouts", [])),
                    "distance": fitness_stats.get("distance", 0.0),
                    "average_active_session_duration": fitness_stats.get("average_active_session_duration", 0.0),
                    "peak_activity_hour": (
                        report.get("peak_activity_time", {}).get("hour")
                        if report.get("peak_activity_time") else None
                    ),
                }

            # If no report found, return zeros (no random data)
            return {
                "steps": 0,
                "active_energy": 0.0,
                "active_duration": 0,
                "workouts_count": 0,
                "distance": 0.0,
                "average_active_session_duration": 0.0,
                "peak_activity_hour": None,
            }

        except Exception as e:
            print(f"Error getting real fitness data: {str(e)}")
            # Return zeros on error (no random data)
            return {
                "steps": 0,
                "active_energy": 0.0,
                "active_duration": 0,
                "workouts_count": 0,
                "distance": 0.0,
                "average_active_session_duration": 0.0,
                "peak_activity_hour": None,
            }

    def _build_analysis_prompt(
        self,
        enrollment: WeightLossAgentEnrollment,
        daily_reports: List[Dict],
        latest_report: Optional[InbodyReport],
    ) -> str:
        """Build analysis prompt for AI"""

        # Calculate age from date of birth
        age = None
        if enrollment.patient.dob:
            today = date.today()
            age = today.year - enrollment.patient.dob.year - ((today.month, today.day) < (enrollment.patient.dob.month, enrollment.patient.dob.day))

        prompt = f"""
        Analyze the weight loss progress for patient:

        Patient Info:
        - Age: {age if age else 'Unknown'}
        - Gender: {enrollment.patient.gender}
        - Target Weight: {enrollment.target_weight_kg} kg
        - Target BMI: {enrollment.target_bmi}
        - Program Goals: {enrollment.program_goals or 'Not specified'}

        Daily Reports Summary:
        {len(daily_reports)} days of data available

        Latest Inbody Report:
        """

        if latest_report and latest_report.measurements:
            prompt += "\nMeasurements:\n"
            for measurement in latest_report.measurements:
                prompt += f"- {measurement.measurement_type}: {measurement.value} {measurement.unit}\n"

        prompt += "\nDaily activity summary:\n"
        for day in daily_reports[-7:]:  # Last 7 days
            prompt += f"Date: {day['date']}\n"
            if day['meal_data']:
                prompt += f"- Meals: {day['meal_data']['meals_count']}, Calories: {day['meal_data']['total_calories']}\n"
            if day['fitness_data']:
                prompt += f"- Steps: {day['fitness_data']['steps']}, Active Energy: {day['fitness_data']['active_energy']} kcal\n"

        return prompt

    async def upload_inbody_image_to_s3(self, image_file, enrollment_id: UUID) -> str:
        """Upload inbody image to S3 and return the URL"""
        try:
            # Read file content
            file_content = await image_file.read()

            # Generate unique filename
            from uuid import uuid4
            file_extension = image_file.filename.split('.')[-1] if '.' in image_file.filename else 'jpg'
            unique_filename = f"inbody-reports/{enrollment_id}/{uuid4()}.{file_extension}"

            # For testing: return a mock URL instead of uploading to S3
            # TODO: Remove this for production and use actual S3 upload
            mock_s3_url = f"https://aihealth-dev.s3.amazonaws.com/{unique_filename}"
            print(f"Mock S3 upload - would upload to: {mock_s3_url}")
            return mock_s3_url

            # Original S3 upload code (commented out for testing)
            """
            # Upload to S3
            s3_url = upload_file_to_s3(
                file_bytes=file_content,
                bucket_name="aihealth-dev",
                file_name=unique_filename,
                content_type=image_file.content_type or "image/jpeg"
            )

            if not s3_url:
                raise_http_exception(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    message="Failed to upload image to S3"
                )

            return s3_url
            """

        except Exception as e:
            print(f"S3 upload error: {str(e)}")
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Error uploading image: {str(e)}"
            )

    async def chat_with_weight_loss_agent(
        self,
        enrollment_id: UUID,
        user_id: str,
        conversation_id: str,
        user_question: str,
    ) -> Dict:
        """Handle chatbot conversations about weight loss progress and reports"""
        
        async with self.postgres_store.get_session() as session:
            # Get enrollment with related data
            enrollment = await session.get(
                WeightLossAgentEnrollment,
                enrollment_id,
                options=[
                    joinedload(WeightLossAgentEnrollment.patient),
                    joinedload(WeightLossAgentEnrollment.inbody_reports).joinedload(InbodyReport.measurements),
                    joinedload(WeightLossAgentEnrollment.inbody_reports).joinedload(InbodyReport.health_indicators),
                ]
            )

            if not enrollment:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found"
                )

            # Get recent daily reports (last 30 days)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            
            daily_reports = await self.get_daily_reports_data(
                UUID(str(enrollment.patient_id)), start_date, end_date
            )

            # Get latest inbody report
            latest_report = None
            latest_report_summary = None
            if enrollment.inbody_reports:
                latest_report = max(enrollment.inbody_reports, key=lambda r: r.report_date)
                latest_report_summary = {
                    "report_id": str(latest_report.report_id),
                    "report_date": latest_report.report_date.isoformat(),
                    "processed": latest_report.processed,
                    "measurements": [
                        {
                            "type": m.measurement_type,
                            "value": m.value,
                            "unit": m.unit,
                            "normal_range": f"{m.normal_min}-{m.normal_max}" if m.normal_min and m.normal_max else None
                        } for m in latest_report.measurements[:10]  # Limit to first 10 measurements
                    ],
                    "health_indicators": [
                        {
                            "name": h.indicator_name,
                            "abnormal": h.is_abnormal,
                            "level": h.abnormality_level,
                            "explanation": h.analysis_explanation
                        } for h in latest_report.health_indicators if h.is_abnormal
                    ]
                }

            # Initialize AI conversation service
            ai_service = AiConversationService(
                conversation_type="weight-loss-agent",
                ai_model_provider="openai",
                selected_ai_model="gpt-4o"
            )

            # Create comprehensive context with enrollment and report data
            context_data = {
                "enrollment_info": {
                    "target_weight": enrollment.target_weight_kg,
                    "target_bmi": enrollment.target_bmi,
                    "program_goals": enrollment.program_goals,
                    "enrollment_date": enrollment.enrollment_date.isoformat(),
                    "days_enrolled": (datetime.now() - enrollment.enrollment_date).days,
                    "current_weight": latest_report_summary.get("measurements", [{}])[0].get("value") if latest_report_summary and latest_report_summary.get("measurements") else None,
                },
                "patient_info": {
                    "age": (datetime.now().date() - enrollment.patient.dob).days // 365 if enrollment.patient.dob else None,
                    "gender": enrollment.patient.gender,
                    "name": f"{enrollment.patient.first_name} {enrollment.patient.last_name}" if enrollment.patient.first_name else "Patient",
                },
                "recent_activity": {
                    "last_7_days": daily_reports[-7:] if len(daily_reports) >= 7 else daily_reports,
                    "last_30_days": daily_reports,
                    "total_days_with_data": len([d for d in daily_reports if d.get("meal_data") or d.get("fitness_data")]),
                    "average_daily_calories": sum([
                        d.get("meal_data", {}).get("total_calories", 0)
                        for d in daily_reports[-7:] if d.get("meal_data")
                    ]) / max(1, len([d for d in daily_reports[-7:] if d.get("meal_data")])),
                    "average_daily_steps": sum([
                        d.get("fitness_data", {}).get("steps", 0)
                        for d in daily_reports[-7:] if d.get("fitness_data")
                    ]) / max(1, len([d for d in daily_reports[-7:] if d.get("fitness_data")])),
                    "total_workouts_last_week": sum([
                        d.get("fitness_data", {}).get("workouts_count", 0)
                        for d in daily_reports[-7:] if d.get("fitness_data")
                    ]),
                },
                "latest_inbody_report": latest_report_summary,
                "health_summary": {
                    "total_reports": len(enrollment.inbody_reports),
                    "latest_report_date": latest_report.report_date.isoformat() if latest_report else None,
                    "processed_reports": len([r for r in enrollment.inbody_reports if r.processed]),
                    "abnormal_indicators": latest_report_summary.get("health_indicators", []) if latest_report_summary else [],
                },
                "question_type": "weight_loss_chatbot",
                "conversation_context": {
                    "is_follow_up": len(conversation_id.split("_")) > 2,  # Check if this is part of an ongoing conversation
                    "query_type": self._classify_query_type(user_question),
                }
            }

            # Generate AI response with enhanced context
            try:
                ai_response = await ai_service.generate_response(
                    patient_id=str(enrollment.patient_id),
                    user_id=user_id,
                    conversation_id=conversation_id,
                    human_input=user_question,
                    conversation_type="weight-loss-agent",
                    additional_context=context_data
                )

                # If AI response is empty or generic, provide a more specific fallback
                if not ai_response.get("response") or ai_response.get("response") == "I'm sorry, I couldn't generate a response at this time.":
                    # Generate a contextual fallback response using available data
                    fallback_context = self._generate_contextual_fallback(
                        user_question, context_data, enrollment, daily_reports, latest_report
                    )
                    ai_response = await ai_service.generate_response(
                        patient_id=str(enrollment.patient_id),
                        user_id=user_id,
                        conversation_id=f"{conversation_id}_fallback",
                        human_input=f"{user_question}\n\nContext: {fallback_context}",
                        conversation_type="weight-loss-agent",
                        additional_context=context_data
                    )

            except Exception as ai_error:
                print(f"AI service error: {str(ai_error)}")
                # Generate contextual fallback response
                fallback_context = self._generate_contextual_fallback(
                    user_question, context_data, enrollment, daily_reports, latest_report
                )

                # Use a simple direct AI call for fallback
                try:
                    from langchain_openai import ChatOpenAI
                    from decouple import config
                    from pydantic import SecretStr
                    from langchain_core.messages import HumanMessage

                    fallback_model = ChatOpenAI(
                        model="gpt-4o",
                        temperature=0.7,
                        api_key=SecretStr(str(config("OPENAI_API_KEY"))),
                        max_tokens=500,
                    )

                    fallback_prompt = f"""
                    You are a weight loss specialist AI assistant. A user asked: "{user_question}"

                    Based on this context about their health data:
                    {fallback_context}

                    Please provide a helpful, personalized response about their weight loss journey.
                    Be encouraging, specific, and actionable in your advice.
                    """

                    fallback_response = await fallback_model.ainvoke([HumanMessage(content=fallback_prompt)])

                    ai_response = {
                        "response": fallback_response.content,
                        "metadata": {"confidence_score": 0.6, "is_fallback": True},
                        "follow_up_questions": []
                    }

                except Exception as fallback_error:
                    print(f"Fallback AI error: {str(fallback_error)}")
                    ai_response = {
                        "response": self._generate_basic_fallback_response(user_question, context_data),
                        "metadata": {"confidence_score": 0.3, "is_fallback": True},
                        "follow_up_questions": []
                    }

            return {
                "response": ai_response.get("response", "I'm sorry, I couldn't generate a response at this time."),
                "confidence_score": ai_response.get("metadata", {}).get("confidence_score"),
                "tags": ai_response.get("metadata", {}).get("tags", []),
                "citations": ai_response.get("metadata", {}).get("citations", []),
                "follow_up_questions": ai_response.get("follow_up_questions", []),
                "query_classification": context_data["conversation_context"]["query_type"],
                "data_used": {
                    "inbody_reports": len(enrollment.inbody_reports),
                    "daily_reports": len(daily_reports),
                    "days_with_meal_data": len([d for d in daily_reports if d.get("meal_data")]),
                    "days_with_fitness_data": len([d for d in daily_reports if d.get("fitness_data")]),
                    "latest_report_date": latest_report.report_date.isoformat() if latest_report else None,
                },
                "fitness_summary": {
                    "average_weekly_steps": context_data["recent_activity"]["average_daily_steps"] * 7,
                    "total_weekly_workouts": context_data["recent_activity"]["total_workouts_last_week"],
                    "days_with_activity": len([d for d in daily_reports[-7:] if d.get("fitness_data") and d.get("fitness_data", {}).get("steps", 0) > 0]),
                    "most_active_hour": max([
                        d.get("fitness_data", {}).get("peak_activity_hour")
                        for d in daily_reports[-7:] if d.get("fitness_data") and d.get("fitness_data", {}).get("peak_activity_hour")
                    ], default=None),
                },
                "has_recent_reports": len(daily_reports) > 0,
                "has_inbody_report": latest_report is not None,
                "days_of_data": len(daily_reports),
                "enrollment_days": (datetime.now() - enrollment.enrollment_date).days,
                "query_type": context_data["conversation_context"]["query_type"],
                "health_insights": {
                    "current_weight": context_data["enrollment_info"]["current_weight"],
                    "target_weight": enrollment.target_weight_kg,
                    "weight_difference": (
                        context_data["enrollment_info"]["current_weight"] - enrollment.target_weight_kg
                        if context_data["enrollment_info"]["current_weight"] else None
                    ),
                    "days_to_goal": None,  # Could be calculated based on progress
                }
            }

    async def agentic_weight_loss_coach(
        self,
        enrollment_id: UUID,
        user_input: str,
        user_id: str,
        conversation_id: Optional[str] = None,
    ) -> Dict:
        """
        Agentic weight loss coach - single API that orchestrates all functionality

        This agent:
        1. Monitors all health data (inbody, meals, fitness, vitals)
        2. Maintains conversation state and user preferences
        3. Asks intelligent questions about preferences and constraints
        4. Provides personalized exercise and diet recommendations
        5. Tracks progress and adjusts recommendations over time
        """

        # Generate conversation ID if not provided
        if not conversation_id:
            conversation_id = f"agent_{enrollment_id}_{datetime.now().isoformat()}"

        # Get or initialize agent state
        agent_state = self._get_agent_state(conversation_id)

        # Get comprehensive health data
        health_context = await self._gather_health_context(enrollment_id)

        # Analyze user input and determine next action
        agent_decision = await self._analyze_user_input(
            user_input, agent_state, health_context
        )

        # Execute the appropriate action
        response = await self._execute_agent_action(
            agent_decision, enrollment_id, user_id, conversation_id, health_context
        )

        # Update agent state
        self._update_agent_state(conversation_id, agent_state, agent_decision, response)

        return response

    async def _gather_health_context(self, enrollment_id: UUID) -> Dict:
        """Gather comprehensive health context from all available sources"""

        async with self.postgres_store.get_session() as session:
            # Get enrollment with all related data
            enrollment = await session.get(
                WeightLossAgentEnrollment,
                enrollment_id,
                options=[
                    joinedload(WeightLossAgentEnrollment.patient),
                    joinedload(WeightLossAgentEnrollment.inbody_reports).joinedload(InbodyReport.measurements),
                    joinedload(WeightLossAgentEnrollment.inbody_reports).joinedload(InbodyReport.health_indicators),
                ]
            )

            if not enrollment:
                raise_http_exception(status_code=404, message="Enrollment not found")

            # Get recent daily data (last 30 days)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=30)
            daily_reports = await self.get_daily_reports_data(
                enrollment.patient_id, start_date, end_date
            )

            # Get latest inbody data
            latest_inbody = None
            if enrollment.inbody_reports:
                latest_inbody = max(enrollment.inbody_reports, key=lambda r: r.report_date)

            return {
                "enrollment": {
                    "id": str(enrollment_id),
                    "target_weight": enrollment.target_weight_kg,
                    "target_bmi": enrollment.target_bmi,
                    "goals": enrollment.program_goals,
                    "enrolled_days": (datetime.now() - enrollment.enrollment_date).days,
                },
                "patient": {
                    "age": (datetime.now().date() - enrollment.patient.dob).days // 365 if enrollment.patient.dob else None,
                    "gender": enrollment.patient.gender,
                    "current_weight": self._extract_current_weight(latest_inbody),
                },
                "inbody_reports": len(enrollment.inbody_reports),
                "latest_inbody": self._format_inbody_data(latest_inbody),
                "daily_reports": daily_reports[-7:],  # Last 7 days
                "health_trends": self._analyze_health_trends(daily_reports, latest_inbody),
            }

    def _extract_current_weight(self, latest_inbody: Optional[InbodyReport]) -> Optional[float]:
        """Extract current weight from latest inbody report"""
        if not latest_inbody or not latest_inbody.measurements:
            return None

        # Look for weight measurement
        for measurement in latest_inbody.measurements:
            if measurement.measurement_type.lower() in ['weight', 'body weight']:
                return measurement.value
        return None

    def _format_inbody_data(self, inbody_report: Optional[InbodyReport]) -> Optional[Dict]:
        """Format inbody report data for agent context"""
        if not inbody_report:
            return None

        return {
            "report_date": inbody_report.report_date.isoformat(),
            "measurements": [
                {
                    "type": m.measurement_type,
                    "value": m.value,
                    "unit": m.unit,
                    "normal_range": f"{m.normal_min}-{m.normal_max}" if m.normal_min and m.normal_max else None
                } for m in inbody_report.measurements[:10]
            ],
            "health_indicators": [
                {
                    "name": h.indicator_name,
                    "abnormal": h.is_abnormal,
                    "level": h.abnormality_level,
                    "explanation": h.analysis_explanation
                } for h in inbody_report.health_indicators if h.is_abnormal
            ],
            "processed": inbody_report.processed
        }

    def _analyze_health_trends(self, daily_reports: List[Dict], latest_inbody: Optional[InbodyReport]) -> Dict:
        """Analyze health trends from daily reports and inbody data"""
        trends = {
            "avg_daily_calories": 0,
            "avg_steps": 0,
            "weight_trend": "stable",
            "activity_level": "moderate",
            "data_days": len(daily_reports),
        }

        if daily_reports:
            # Calculate averages
            calories_data = [d.get("meal_data", {}).get("total_calories", 0) for d in daily_reports if d.get("meal_data")]
            steps_data = [d.get("fitness_data", {}).get("steps", 0) for d in daily_reports if d.get("fitness_data")]

            if calories_data:
                trends["avg_daily_calories"] = sum(calories_data) / len(calories_data)
            if steps_data:
                trends["avg_steps"] = sum(steps_data) / len(steps_data)

            # Determine activity level
            if trends["avg_steps"] > 10000:
                trends["activity_level"] = "high"
            elif trends["avg_steps"] > 5000:
                trends["activity_level"] = "moderate"
            else:
                trends["activity_level"] = "low"

        return trends

    def _get_agent_state(self, conversation_id: str) -> Dict:
        """Get or initialize agent conversation state"""
        if conversation_id not in self.agent_memory:
            self.agent_memory[conversation_id] = {
                "conversation_stage": "initial_greeting",
                "user_preferences": {
                    "fitness_level": None,
                    "available_equipment": [],
                    "time_commitment": None,
                    "preferred_exercises": [],
                    "dietary_restrictions": [],
                    "motivation_level": None,
                    "past_experiences": [],
                },
                "collected_data": {
                    "questions_asked": [],
                    "answers_received": [],
                    "recommendations_given": [],
                    "progress_tracking": [],
                },
                "current_focus": "assessment",
                "last_interaction": datetime.now(),
            }
        return self.agent_memory[conversation_id]

    async def _analyze_user_input(self, user_input: str, agent_state: Dict, health_context: Dict) -> Dict:
        """Analyze user input and determine next agent action"""

        # Classify the input
        input_type = self._classify_user_input(user_input)

        # Determine next action based on conversation stage and input
        stage = agent_state["conversation_stage"]

        if stage == "initial_greeting":
            return {
                "action": "ask_preferences",
                "reason": "First interaction - need to understand user preferences",
                "next_stage": "gathering_preferences"
            }

        elif stage == "gathering_preferences":
            if input_type in ["preference_answer", "exercise_preference"]:
                return {
                    "action": "process_preference",
                    "reason": "User provided preference information",
                    "next_stage": "assessment_complete"
                }
            else:
                return {
                    "action": "ask_clarifying_question",
                    "reason": "Need more specific preference information",
                    "next_stage": "gathering_preferences"
                }

        elif stage == "assessment_complete":
            if input_type == "progress_question":
                return {
                    "action": "provide_progress_report",
                    "reason": "User asked about progress",
                    "next_stage": "assessment_complete"
                }
            elif input_type in ["exercise_request", "diet_request"]:
                return {
                    "action": "provide_recommendation",
                    "reason": "User requested specific recommendations",
                    "next_stage": "assessment_complete"
                }
            else:
                return {
                    "action": "provide_general_guidance",
                    "reason": "General conversation or question",
                    "next_stage": "assessment_complete"
                }

        # Default action
        return {
            "action": "ask_follow_up",
            "reason": "Continue conversation naturally",
            "next_stage": stage
        }

    def _classify_user_input(self, user_input: str) -> str:
        """Classify the type of user input"""
        input_lower = user_input.lower()

        # Preference-related inputs
        if any(word in input_lower for word in ["like", "prefer", "enjoy", "good at", "comfortable with"]):
            return "preference_answer"

        # Exercise-specific inputs
        if any(word in input_lower for word in ["run", "walk", "gym", "weights", "yoga", "swim", "bike"]):
            return "exercise_preference"

        # Progress questions
        if any(word in input_lower for word in ["progress", "how am i doing", "results", "weight loss"]):
            return "progress_question"

        # Specific requests
        if any(word in input_lower for word in ["exercise", "workout", "recommend", "suggest"]):
            return "exercise_request"

        if any(word in input_lower for word in ["diet", "food", "eat", "meal"]):
            return "diet_request"

        # Questions
        if "?" in user_input or any(word in input_lower for word in ["what", "how", "when", "why", "can i"]):
            return "question"

        return "general_statement"

    async def _execute_agent_action(
        self,
        agent_decision: Dict,
        enrollment_id: UUID,
        user_id: str,
        conversation_id: str,
        health_context: Dict
    ) -> Dict:
        """Execute the determined agent action"""

        action = agent_decision["action"]

        if action == "ask_preferences":
            return await self._ask_user_preferences(health_context)

        elif action == "process_preference":
            return await self._process_user_preference(agent_decision, health_context)

        elif action == "ask_clarifying_question":
            return await self._ask_clarifying_question(agent_decision, health_context)

        elif action == "provide_progress_report":
            return await self._provide_progress_report(health_context)

        elif action == "provide_recommendation":
            return await self._provide_personalized_recommendation(agent_decision, health_context)

        elif action == "provide_general_guidance":
            return await self._provide_general_guidance(agent_decision, health_context)

        else:
            return await self._provide_fallback_response(health_context)

    async def _ask_user_preferences(self, health_context: Dict) -> Dict:
        """Ask user about their preferences and constraints"""
        return {
            "response": """Hello! I'm your personal weight loss coach. To provide you with the best recommendations, I need to understand your preferences and lifestyle. Let me ask you a few questions:

1. What's your current fitness level? (Beginner, Intermediate, Advanced)
2. What type of exercises do you enjoy or prefer? (e.g., cardio, strength training, yoga, sports)
3. How much time can you dedicate to exercise each day/week?
4. Do you have access to a gym or prefer home workouts?
5. Any injuries, health conditions, or exercises you should avoid?
6. What's your primary goal? (Weight loss, muscle gain, overall fitness)

Feel free to answer any or all of these, and I'll tailor my recommendations accordingly!""",
            "agent_action": "gathering_preferences",
            "questions_asked": [
                "fitness_level", "exercise_preferences", "time_commitment",
                "equipment_access", "limitations", "primary_goal"
            ],
            "next_expected_input": "preference_answers",
            "conversation_stage": "gathering_preferences"
        }

    async def _process_user_preference(self, agent_decision: Dict, health_context: Dict) -> Dict:
        """Process user preference and provide initial recommendations"""
        return {
            "response": """Thank you for sharing your preferences! Based on what you've told me and your health data, here's my initial assessment:

**Your Profile:**
- Current fitness level: [Based on your input]
- Available time: [Based on your input]
- Preferences: [Based on your input]

**Recommended Starting Plan:**
1. **Daily Activity:** Aim for 8,000-10,000 steps per day
2. **Exercise Routine:** [Personalized based on preferences]
3. **Nutrition Focus:** [Based on your meal data]

Would you like me to create a specific workout plan for this week, or do you have questions about any of these recommendations?""",
            "agent_action": "processed_preferences",
            "recommendations": [
                "daily_step_goal",
                "exercise_routine",
                "nutrition_guidance"
            ],
            "conversation_stage": "assessment_complete"
        }

    async def _provide_progress_report(self, health_context: Dict) -> Dict:
        """Provide comprehensive progress report"""
        enrollment = health_context["enrollment"]
        patient = health_context["patient"]
        trends = health_context["health_trends"]

        progress_summary = f"""
**Progress Report - {enrollment['enrolled_days']} days enrolled**

**Current Status:**
- Target Weight: {enrollment['target_weight']} kg
- Current Weight: {patient['current_weight'] or 'Not available'} kg
- Average Daily Calories: {trends['avg_daily_calories']:.0f}
- Average Daily Steps: {trends['avg_steps']:.0f}
- Activity Level: {trends['activity_level']}

**Health Trends:**
- Data points available: {trends['data_days']} days
- Inbody reports: {health_context['inbody_reports']}

**Recommendations:**
Based on your data, you're doing {'well' if trends['activity_level'] == 'high' else 'okay'}. Let's focus on consistency and gradual improvements.
"""

        return {
            "response": progress_summary,
            "agent_action": "progress_report_provided",
            "progress_metrics": {
                "days_enrolled": enrollment["enrolled_days"],
                "avg_calories": trends["avg_daily_calories"],
                "avg_steps": trends["avg_steps"],
                "activity_level": trends["activity_level"],
                "data_completeness": f"{trends['data_days']}/30 days"
            },
            "conversation_stage": "assessment_complete"
        }

    async def _provide_personalized_recommendation(self, agent_decision: Dict, health_context: Dict) -> Dict:
        """Provide personalized exercise or diet recommendations"""
        trends = health_context["health_trends"]

        if trends["activity_level"] == "low":
            exercise_rec = """
**Exercise Recommendations for Beginners:**
1. **Walking Program:** Start with 20-30 minutes brisk walking daily
2. **Bodyweight Exercises:** 3x per week (squats, push-ups, planks)
3. **Flexibility:** 10 minutes daily stretching
4. **Progression:** Increase duration by 5 minutes weekly
"""
        elif trends["activity_level"] == "moderate":
            exercise_rec = """
**Exercise Recommendations for Intermediate:**
1. **Cardio:** 30-45 minutes, 4-5 days/week (mix of walking, cycling, swimming)
2. **Strength Training:** 3x per week, full body workouts
3. **HIIT Sessions:** 20-30 minutes, 2x per week
4. **Active Recovery:** Light yoga or walking on rest days
"""
        else:
            exercise_rec = """
**Exercise Recommendations for Advanced:**
1. **High-Intensity Training:** 45-60 minutes, 5-6 days/week
2. **Strength Training:** 4-5x per week, split routines
3. **Sports/Activity:** Incorporate preferred sports 2-3x per week
4. **Recovery:** Active recovery and mobility work
"""

        return {
            "response": f"Based on your current activity level ({trends['activity_level']}) and health data, here are my recommendations:\n\n{exercise_rec}\n\n**Nutrition Notes:**\n- Current average: {trends['avg_daily_calories']:.0f} calories/day\n- Focus on whole foods and portion control\n- Stay hydrated and consider meal timing\n\nHow does this plan sound to you?",
            "agent_action": "recommendations_provided",
            "recommendations": {
                "exercise_plan": exercise_rec.strip(),
                "nutrition_focus": "whole_foods_portion_control",
                "activity_level": trends["activity_level"],
                "customized": True
            },
            "conversation_stage": "assessment_complete"
        }

    async def _provide_general_guidance(self, agent_decision: Dict, health_context: Dict) -> Dict:
        """Provide general guidance and ask follow-up questions"""
        return {
            "response": """I'm here to help you with your weight loss journey! I can assist with:

**Exercise Planning:**
- Personalized workout routines
- Progress tracking
- Exercise modifications

**Nutrition Guidance:**
- Meal planning
- Calorie tracking
- Healthy eating habits

**Motivation & Support:**
- Progress reports
- Goal setting
- Accountability

**Health Monitoring:**
- Inbody report analysis
- Trend identification
- Health insights

What specific aspect would you like help with today? Or would you like me to review your recent progress?""",
            "agent_action": "general_guidance_provided",
            "available_services": [
                "exercise_planning",
                "nutrition_guidance",
                "progress_tracking",
                "health_monitoring",
                "motivation_support"
            ],
            "conversation_stage": "assessment_complete"
        }

    async def _ask_clarifying_question(self, agent_decision: Dict, health_context: Dict) -> Dict:
        """Ask clarifying questions to better understand user needs"""
        return {
            "response": "I'd love to provide more specific recommendations, but I need a bit more information. Could you tell me:\n\n1. What type of exercises do you currently enjoy?\n2. How much time do you have available for workouts?\n3. Are there any exercises or activities you particularly dislike?\n4. What's your main motivation for starting this journey?\n\nThis will help me create a plan that you'll actually enjoy and stick with!",
            "agent_action": "clarifying_questions_asked",
            "questions_asked": [
                "exercise_enjoyment",
                "time_availability",
                "exercise_dislikes",
                "motivation"
            ],
            "conversation_stage": "gathering_preferences"
        }

    async def _provide_fallback_response(self, health_context: Dict) -> Dict:
        """Provide fallback response when action is unclear"""
        return {
            "response": "I'm here to support your weight loss journey! I have access to your health data and can provide personalized recommendations for exercise, nutrition, and progress tracking. What would you like help with today?",
            "agent_action": "fallback_response",
            "capabilities": [
                "exercise_recommendations",
                "meal_planning",
                "progress_tracking",
                "health_analysis",
                "motivation_support"
            ],
            "conversation_stage": "assessment_complete"
        }

    def _update_agent_state(self, conversation_id: str, agent_state: Dict, agent_decision: Dict, response: Dict):
        """Update the agent conversation state"""
        agent_state["last_interaction"] = datetime.now()
        agent_state["conversation_stage"] = response.get("conversation_stage", agent_state["conversation_stage"])
        agent_state["collected_data"]["questions_asked"].extend(response.get("questions_asked", []))
        agent_state["collected_data"]["recommendations_given"].extend(response.get("recommendations", []))

    async def process_and_analyze_inbody_report(
        self,
        enrollment_id: UUID,
        report_file,
        user_id: str
    ) -> InbodyReportAnalysisResult:
        """Process uploaded inbody report file with base64 conversion first, then get AI analysis - returns GPT response first, then stores data"""

        # WORKFLOW: Base64 First → AI Analysis → User Review → Database Storage
        try:
            # Step 1: Read file content and convert to base64 FIRST
            print("Step 1: Reading file content...")
            file_content = await report_file.read()
            file_name = report_file.filename
            content_type = report_file.content_type

            print(f"File details: {file_name}, type: {content_type}, size: {len(file_content)} bytes")

            # Convert file content to base64 for AI processing
            print("Step 2: Converting file to base64...")
            import base64
            file_content_b64 = base64.b64encode(file_content).decode('utf-8')
            print(f"File successfully encoded to base64, length: {len(file_content_b64)} characters")

            # Validate base64 conversion
            if not file_content_b64:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Failed to convert file to base64 format"
                )

            # Step 3: Prepare for vision analysis (no need for text prompt with base64)
            print("Step 3: Preparing for GPT-4 Vision analysis...")

            # Handle different file types
            if content_type == "application/pdf":
                print("PDF file detected - using text extraction approach")
                # For PDFs, we might need to extract text first or use a different approach
                # For now, let's try sending as image (some PDFs might work)
                pass

            print("Step 4: Sending image to GPT-4 Vision for analysis...")

            # Use GPT-4 Vision for image analysis instead of sending base64 in text
            try:
                from langchain_openai import ChatOpenAI
                from decouple import config
                from pydantic import SecretStr
                from langchain_core.messages import HumanMessage

                # Initialize GPT-4 Vision model
                vision_model = ChatOpenAI(
                    model="gpt-4o",  # GPT-4o has vision capabilities
                    temperature=0.3,
                    api_key=SecretStr(str(config("OPENAI_API_KEY"))),
                    max_tokens=2000,  # Limit output tokens
                )

                # Create message with image URL for vision analysis
                # For base64 images, we need to format it properly
                image_url = f"data:{content_type};base64,{file_content_b64}"

                # Create a simpler prompt for vision analysis
                vision_prompt = """
                Analyze this Inbody report image and extract the key health metrics. Focus on:

                **Key Metrics to Extract:**
                1. Current Weight and BMI
                2. Target Weight (if visible on the report)
                3. Body Fat Percentage and Skeletal Muscle Mass
                4. Body Water and Protein percentages
                5. Visceral Fat Level and Basal Metabolic Rate
                6. Any other visible measurements

                **Analysis Required:**
                1. Overall Health Score (0-100)
                2. Strengths (2 main positive indicators)
                3. Areas for Improvement (2 main concerns)
                4. Priority Recommendations (2 actionable items)
                5. Risk Factors (any concerning values)

                If you can see a target weight on the report, please extract it clearly as "Target Weight: X kg".
                Provide a structured analysis with specific numbers and clear recommendations.
                """

                # Create message with image
                message = HumanMessage(
                    content=[
                        {"type": "text", "text": vision_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url}
                        }
                    ]
                )

                # Get AI response
                ai_response_raw = await vision_model.ainvoke([message])
                ai_response_text = ai_response_raw.content

                print(f"Vision analysis completed successfully. Response length: {len(ai_response_text)}")

                # Parse the AI response to extract actual metric values
                confidence_score = 0.9  # Higher confidence for vision analysis
                extracted_metrics = {}
                recommendations = []
                risk_factors = []

                # Extract actual values using regex patterns
                import re

                # Weight extraction
                weight_match = re.search(r'weight[:\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)', ai_response_text, re.IGNORECASE)
                if weight_match:
                    extracted_metrics["weight"] = f"{weight_match.group(1)} {weight_match.group(2)}"

                # Target Weight extraction
                target_weight_match = re.search(r'target\s+weight[:\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)', ai_response_text, re.IGNORECASE)
                if target_weight_match:
                    extracted_metrics["target_weight"] = f"{target_weight_match.group(1)} {target_weight_match.group(2)}"

                # BMI extraction
                bmi_match = re.search(r'bmi[:\s]+([\d.]+)', ai_response_text, re.IGNORECASE)
                if bmi_match:
                    extracted_metrics["bmi"] = bmi_match.group(1)

                # Body Fat Percentage extraction
                body_fat_match = re.search(r'body fat[:\s]+([\d.]+)\s*%', ai_response_text, re.IGNORECASE)
                if body_fat_match:
                    extracted_metrics["body_fat_percentage"] = f"{body_fat_match.group(1)}%"

                # Skeletal Muscle Mass extraction
                muscle_match = re.search(r'(?:skeletal\s+)?muscle mass[:\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)', ai_response_text, re.IGNORECASE)
                if muscle_match:
                    extracted_metrics["muscle_mass"] = f"{muscle_match.group(1)} {muscle_match.group(2)}"

                # Body Water extraction
                water_match = re.search(r'body water[:\s]+([\d.]+)\s*%', ai_response_text, re.IGNORECASE)
                if water_match:
                    extracted_metrics["body_water"] = f"{water_match.group(1)}%"

                # Visceral Fat Level extraction
                visceral_match = re.search(r'visceral fat[:\s]+([\d.]+)', ai_response_text, re.IGNORECASE)
                if visceral_match:
                    extracted_metrics["visceral_fat"] = visceral_match.group(1)

                # Basal Metabolic Rate extraction
                bmr_match = re.search(r'(?:basal metabolic rate|bmr)[:\s]+([\d.]+)\s*(kcal|calories?)', ai_response_text, re.IGNORECASE)
                if bmr_match:
                    extracted_metrics["basal_metabolic_rate"] = f"{bmr_match.group(1)} {bmr_match.group(2) if bmr_match.group(2) else 'kcal'}"

                # Calculate confidence score based on extracted metrics
                metric_count = len(extracted_metrics)
                if metric_count >= 5:
                    confidence_score = 0.95  # High confidence with many metrics
                elif metric_count >= 3:
                    confidence_score = 0.85  # Good confidence with several metrics
                elif metric_count >= 1:
                    confidence_score = 0.7   # Moderate confidence with some metrics
                else:
                    confidence_score = 0.5   # Low confidence with few or no metrics

                # Extract recommendations from the response
                if "recommend" in ai_response_text.lower():
                    # Try to extract specific recommendations
                    rec_patterns = [
                        r'recommendations?[:\s]*(.*?)(?:\n|$)',
                        r'priority recommendations?[:\s]*(.*?)(?:\n|$)',
                        r'strengths?[:\s]*(.*?)(?:\n|$)',
                        r'areas for improvement[:\s]*(.*?)(?:\n|$)',
                    ]
                    for pattern in rec_patterns:
                        rec_match = re.search(pattern, ai_response_text, re.IGNORECASE | re.DOTALL)
                        if rec_match:
                            rec_text = rec_match.group(1).strip()
                            if rec_text and len(rec_text) > 10:  # Only add meaningful recommendations
                                recommendations.append(rec_text[:200])  # Limit length
                                break

                    if not recommendations:
                        recommendations.append("Follow the personalized recommendations provided in the analysis")

                # Extract risk factors
                if "risk" in ai_response_text.lower() or "concern" in ai_response_text.lower() or "abnormal" in ai_response_text.lower():
                    risk_patterns = [
                        r'risk factors?[:\s]*(.*?)(?:\n|$)',
                        r'concerns?[:\s]*(.*?)(?:\n|$)',
                        r'abnormal[:\s]*(.*?)(?:\n|$)',
                    ]
                    for pattern in risk_patterns:
                        risk_match = re.search(pattern, ai_response_text, re.IGNORECASE | re.DOTALL)
                        if risk_match:
                            risk_text = risk_match.group(1).strip()
                            if risk_text and len(risk_text) > 10:
                                risk_factors.append(risk_text[:200])
                                break

                    if not risk_factors:
                        risk_factors.append("Review identified concerns with healthcare provider")

                ai_response = {
                    "response": ai_response_text,
                    "metadata": {
                        "confidence_score": confidence_score,
                        "extracted_metrics": extracted_metrics,
                        "recommendations": recommendations,
                        "risk_factors": risk_factors
                    }
                }

            except Exception as ai_error:
                print(f"Vision analysis failed: {str(ai_error)}")
                # Provide fallback response
                ai_response = {
                    "response": f"File '{file_name}' has been uploaded successfully. AI vision analysis is currently unavailable, but the report has been stored for future processing.",
                    "metadata": {"confidence_score": 0.0}
                }

            # Return AI response immediately without storing in database yet
            analysis_result = InbodyReportAnalysisResult(
                file_name=file_name,
                processed_at=datetime.now().isoformat(),
                ai_analysis={
                    "summary": ai_response.get("response", "Analysis completed but no detailed response available."),
                    "confidence_score": ai_response.get("metadata", {}).get("confidence_score", 0.0),
                    "extracted_metrics": ai_response.get("metadata", {}).get("extracted_metrics", {}),
                    "recommendations": ai_response.get("metadata", {}).get("recommendations", []),
                    "risk_factors": ai_response.get("metadata", {}).get("risk_factors", []),
                    "structured": True if ai_response.get("metadata", {}).get("confidence_score", 0.0) > 0 else False
                },
                metadata={
                    "content_type": content_type,
                    "file_size": len(file_content),
                    "enrollment_id": str(enrollment_id),
                    "original_filename": file_name,
                    "ready_for_storage": True  # Flag indicating analysis is complete and ready to store
                }
            )

            print(f"Base64 processing workflow completed. Analysis result prepared with file: {analysis_result.file_name}")

            # Step 5: Store the analyzed report in database
            print("Step 5: Storing analyzed report in database...")
            try:
                from lib.schemas.weight_loss_agent import InbodyReportCreate

                # Create report data from analysis result (excluding ai_summary for now due to migration issue)
                report_data = InbodyReportCreate(
                    report_date=datetime.now(),
                    ai_summary=None,  # Temporarily set to None until migration is run
                    original_filename=analysis_result.file_name,
                    file_size=analysis_result.metadata.get("file_size", 0),
                    content_type=analysis_result.metadata.get("content_type", "")
                )

                # Store the report in database
                report = await self.create_inbody_report(enrollment_id, report_data)
                print(f"Report stored in database with ID: {report.report_id}")

                # Update the analysis result with the report ID and storage info
                analysis_result.report_id = str(report.report_id)
                analysis_result.stored_at = datetime.now().isoformat()
                analysis_result.metadata["stored"] = True
                analysis_result.metadata["ai_summary_pending"] = True  # Flag that AI summary needs to be stored later

                print("Report successfully stored in database (AI summary will be added after migration)")
                return analysis_result

            except Exception as storage_error:
                print(f"Failed to store report in database: {str(storage_error)}")
                # Still return the analysis result even if storage fails
                analysis_result.metadata["storage_error"] = str(storage_error)
                analysis_result.metadata["stored"] = False
                return analysis_result

        except Exception as e:
            print(f"Error in process_and_analyze_inbody_report: {str(e)}")
            import traceback
            traceback.print_exc()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to process inbody report: {str(e)}"
            )

    async def store_inbody_report_analysis(
        self,
        enrollment_id: UUID,
        analysis_result: InbodyReportAnalysisResult,
        user_id: str
    ) -> InbodyReportAnalysisResult:
        """Store the analyzed inbody report data in database after user confirmation"""

        try:
            from lib.schemas.weight_loss_agent import InbodyReportCreate

            # Create report data from analysis result (excluding ai_summary for now due to migration issue)
            report_data = InbodyReportCreate(
                report_date=datetime.now(),
                ai_summary=None,  # Temporarily set to None until migration is run
                original_filename=analysis_result.file_name,
                file_size=analysis_result.metadata.get("file_size", 0),
                content_type=analysis_result.metadata.get("content_type", "")
            )

            # Store the report in database
            report = await self.create_inbody_report(enrollment_id, report_data)
            print(f"Report stored in database with ID: {report.report_id}")

            # Update the analysis result with the report ID
            analysis_result.report_id = str(report.report_id)
            analysis_result.stored_at = datetime.now().isoformat()
            analysis_result.metadata["stored"] = True

            return analysis_result

        except Exception as e:
            print(f"Error storing inbody report analysis: {str(e)}")
            import traceback
            traceback.print_exc()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"Failed to store inbody report analysis: {str(e)}"
            )
