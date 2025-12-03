import re
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy import and_, func
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload, selectinload

from motor.motor_asyncio import AsyncIOMotorCollection

from lib.core.clickhouse_store import ClickHouseStore
from lib.core.postgres_store import PostgresStore
from lib.models.patient import Patient
from lib.models.patient_meal import PatientMeal
from lib.models.patient_vital import PatientVital
from lib.schemas.weight_loss_agent import (
    InbodyReportAnalysisResult,
    InbodyReportCreate,
    WeightLossEnrollmentCreate,
    WeightLossEnrollmentUpdate,
)
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.care_provider_profile_service import CareProviderProfileService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.weightloss_agent.analytics_service import AnalyticsService
from lib.models.weight_loss_agent import WeightLossAgentEnrollment
from lib.utils.http_exceptions import raise_http_exception


class WeightLossAgentService:
    """Service for managing weight loss agent functionality using MongoDB"""

    CONFIRMATION_THRESHOLD = 0.85

    def __init__(
        self,
        postgres_store: PostgresStore,
        clickhouse_store: ClickHouseStore,
        enrollments_collection: MongoStore,
        reports_collection: MongoStore,
        interactions_collection: MongoStore,
        progress_analyses_collection: MongoStore,
    ):
        self.postgres_store = postgres_store
        self.clickhouse_store = clickhouse_store
        self.reports_collection = reports_collection
        self.interactions_collection = interactions_collection
        self.progress_analyses_collection = progress_analyses_collection
        self.patient_profile_service = patient_profile_service
        self.care_provider_profile_service = care_provider_profile_service
        self.analytics_service = analytics_service

    def _serialize_enrollment(self, enrollment: WeightLossAgentEnrollment) -> Dict[str, Any]:
        return {
            "enrollment_id": str(enrollment.enrollment_id),
            "patient_id": str(enrollment.patient_id),
            "enrolled_by_care_provider_id": str(enrollment.enrolled_by_care_provider_id),
            "enrollment_date": enrollment.enrollment_date,
            "is_active": enrollment.is_active,
            "program_goals": enrollment.program_goals,
            "target_weight_kg": enrollment.target_weight_kg,
            "target_bmi": enrollment.target_bmi,
            "created_at": enrollment.created_at,
            "updated_at": enrollment.updated_at,
        }

    async def enroll_patient_in_weight_loss_program(
        self,
        enrollment_data: WeightLossEnrollmentCreate,
    ) -> Dict:
        """Enroll a patient in the weight loss program (doctor only) - stores in MongoDB"""

        # Ensure care provider exists and is a doctor via profile service
        care_provider = await self.care_provider_profile_service.fetch_care_provider(
            str(enrollment_data.enrolled_by_care_provider_id)
        )
        if str(care_provider.role).lower() != "doctor":
            raise_http_exception(
                status_code=status.HTTP_403_FORBIDDEN,
                message="Only doctors can enroll patients in weight loss program"
            )

        # Ensure patient exists via profile service (raises if missing)
        await self.patient_profile_service.fetch_patient_profile(
            str(enrollment_data.patient_id)
        )

        async with self.postgres_store.get_session() as session:
            # Verify the care provider is a doctor (still in PostgreSQL)
            care_provider = await session.get(
                CareProvider, enrollment_data.enrolled_by_care_provider_id
            )
            if not care_provider:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Care provider not found",
                )

            if str(care_provider.role).lower() != "doctor":
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="Only doctors can enroll patients in weight loss program",
                )
            )
            if existing.scalar_one_or_none():
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Patient not found",
                )

        # Check if patient already has an active enrollment (in MongoDB)
        existing_enrollment = await self.enrollments_collection.find_one(  # type: ignore
            {"patient_id": str(enrollment_data.patient_id), "is_active": True}
        )

        if existing_enrollment:
            raise_http_exception(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="Patient is already enrolled in weight loss program",
            )
            session.add(enrollment)
            await session.commit()
            await session.refresh(enrollment)

        # Create enrollment document for MongoDB
        enrollment_doc = {
            "enrollment_id": str(uuid4()),
            "patient_id": str(enrollment_data.patient_id),
            "enrolled_by_care_provider_id": str(
                enrollment_data.enrolled_by_care_provider_id
            ),
            "enrollment_date": datetime.now(),
            "is_active": True,
            "program_goals": enrollment_data.program_goals,
            "target_weight_kg": enrollment_data.target_weight_kg,
            "target_bmi": enrollment_data.target_bmi,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }

        # Insert into MongoDB
        await self.enrollments_collection.insert_one(enrollment_doc)  # type: ignore

        # Remove MongoDB _id for response
        enrollment_doc.pop("_id", None)

        return enrollment_doc

    async def update_patient_enrollment(
        self,
        enrollment_id: UUID,
        update_data: WeightLossEnrollmentUpdate,
    ) -> Dict:
        """Update patient enrollment details - MongoDB"""

        # Get enrollment from MongoDB
        enrollment = await self.enrollments_collection.find_one(  # type: ignore
            {"enrollment_id": str(enrollment_id)}
        )

        if not enrollment:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Enrollment not found",
            )

            update_dict = update_data.dict(exclude_unset=True)
            for field, value in update_dict.items():
                setattr(enrollment, field, value)
            enrollment.updated_at = datetime.now()
            await session.commit()
            await session.refresh(enrollment)

        # Update in MongoDB
        await self.enrollments_collection.update_one(
            {"enrollment_id": str(enrollment_id)}, {"$set": update_dict}
        )

        # Get updated enrollment
        updated_enrollment = await self.enrollments_collection.find_one(
            {"enrollment_id": str(enrollment_id)}
        )
        updated_enrollment.pop("_id", None)

        return updated_enrollment

    async def get_patient_enrollment(
        self, enrollment_id: UUID
    ) -> Optional[Dict]:
        """Get patient's weight loss enrollment by enrollment_id - MongoDB"""

        enrollment = await self.enrollments_collection.find_one(
            {"enrollment_id": str(enrollment_id)}
        )

        if enrollment:
            enrollment.pop("_id", None)
            return enrollment

        return None

    async def get_patient_enrollment_by_patient_id(
        self, patient_id: UUID
    ) -> Optional[Dict]:
        """Get patient's active weight loss enrollment by patient_id - MongoDB"""

        enrollment = await self.enrollments_collection.find_one(
            {"patient_id": str(patient_id), "is_active": True}
        )

        if enrollment:
            enrollment.pop("_id", None)
            return enrollment

        return None

    async def create_inbody_report(
        self,
        enrollment_id: UUID,
        report_data: InbodyReportCreate,
    ) -> Dict:
        """Create a new inbody report - MongoDB"""

        # Verify enrollment exists and is active (in MongoDB)
        enrollment = await self.enrollments_collection.find_one(
            {"enrollment_id": str(enrollment_id), "is_active": True}
        )

        if not enrollment:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Active enrollment not found",
            )

        # Create inbody report document
        report_doc = {
            "report_id": str(uuid4()),
            "enrollment_id": str(enrollment_id),
            "patient_id": enrollment["patient_id"],
            "ai_summary": report_data.ai_summary,
            "original_filename": report_data.original_filename,
            "file_size": report_data.file_size,
            "content_type": report_data.content_type,
            "report_date": report_data.report_date,
            "extracted_at": datetime.now(),
            "processed": False,
            "created_at": datetime.now(),
            "measurements": [],  # Will be populated by analysis
            "health_indicators": [],  # Will be populated by analysis
        }

        # Insert into MongoDB
        await self.reports_collection.insert_one(report_doc)

        # Remove MongoDB _id
        report_doc.pop("_id", None)

        return report_doc

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

                daily_data.append(
                    {
                        "date": date_str,
                        "meal_data": (
                            {
                                "meals_count": len(meals),
                                "total_calories": sum(
                                    meal.total_macro_nutritional_value.calories
                                    for meal in meals
                                    if meal.total_macro_nutritional_value
                                    and hasattr(
                                        meal.total_macro_nutritional_value,
                                        "calories",
                                    )
                                ),
                                "meals": [
                                    {
                                        "meal_id": str(meal.id),
                                        "type": meal.type,
                                        "calories": (
                                            meal.total_macro_nutritional_value.calories
                                            if meal.total_macro_nutritional_value
                                            else 0
                                        ),
                                    }
                                    for meal in meals
                                ],
                            }
                            if meals
                            else None
                        ),
                        "fitness_data": fitness_data,
                        "vitals_data": (
                            {
                                "weight": (
                                    vitals[-1].weight
                                    if vitals
                                    and len(vitals) > 0
                                    and vitals[-1].weight
                                    else None
                                ),
                                "blood_pressure": (
                                    {
                                        "systolic": (
                                            vitals[-1].systolic_bp
                                            if vitals
                                            and vitals[-1].systolic_bp
                                            else None
                                        ),
                                        "diastolic": (
                                            vitals[-1].diastolic_bp
                                            if vitals
                                            and vitals[-1].diastolic_bp
                                            else None
                                        ),
                                    }
                                    if vitals
                                    else None
                                ),
                            }
                            if vitals
                            else None
                        ),
                    }
                )

                current_date += timedelta(days=1)

            return daily_data

    async def analyze_weight_loss_progress(
        self,
        enrollment_id: UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        """Analyze weight loss progress using AI - MongoDB"""

        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        # Get enrollment from MongoDB
        enrollment = await self.enrollments_collection.find_one(
            {"enrollment_id": str(enrollment_id)}
        )

        if not enrollment:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Enrollment not found",
            )

        # Get patient info from PostgreSQL
        async with self.postgres_store.get_session() as session:
            patient = await session.get(
                Patient, UUID(enrollment["patient_id"])
            )
            enrollment["patient"] = patient

        # Get daily reports data
        daily_reports = await self.get_daily_reports_data(
            UUID(enrollment["patient_id"]), start_date, end_date
        )

        # Get latest inbody report from MongoDB
        latest_report_cursor = (
            self.reports_collection.find({"enrollment_id": str(enrollment_id)})
            .sort("report_date", -1)
            .limit(1)
        )

        latest_report = None
        async for report in latest_report_cursor:
            latest_report = report
            break

        # Create latest report summary
        latest_report_summary = None
        if latest_report:
            latest_report_summary = {
                "report_id": latest_report.get("report_id"),
                "report_date": (
                    latest_report.get("report_date").isoformat()
                    if latest_report.get("report_date")
                    else None
                ),
                "processed": latest_report.get("processed", False),
                "extraction_confidence": latest_report.get(
                    "extraction_confidence"
                ),
                "abnormal_indicators_count": len(
                    [
                        h
                        for h in latest_report.get("health_indicators", [])
                        if h.get("is_abnormal")
                    ]
                ),
                "measurements_count": len(
                    latest_report.get("measurements", [])
                ),
            }

        # Use AI to analyze the data
        ai_service = AiConversationService(
            conversation_type="weight-loss-agent",
            ai_model_provider="openai",  # Can be configured
            selected_ai_model="gpt-4o",
        )

        analysis_prompt = self._build_structured_analysis_prompt(
            enrollment, daily_reports, latest_report
        )

        # Generate AI analysis
        ai_response = await ai_service.generate_response(
            patient_id=str(enrollment["patient_id"]),
            user_id=str(
                enrollment["enrolled_by_care_provider_id"]
            ),  # Use care provider as user
            conversation_id=f"analysis_{enrollment_id}_{start_date.isoformat()}_{end_date.isoformat()}",
            human_input=analysis_prompt,
            conversation_type="weight-loss-agent",
            additional_context={
                "analysis_type": "weight_loss_progress",
                "enrollment_data": {
                    "target_weight": enrollment.get("target_weight_kg"),
                    "target_bmi": enrollment.get("target_bmi"),
                    "program_goals": enrollment.get("program_goals"),
                    "enrollment_date": (
                        enrollment.get("enrollment_date").isoformat()
                        if enrollment.get("enrollment_date")
                        else None
                    ),
                },
                "daily_reports": daily_reports,
                "latest_inbody_report": (
                    latest_report_summary if latest_report else None
                ),
            },
        )

        # Parse the AI response into structured format
        analysis = self._parse_analysis_response(
            ai_response,
            enrollment_id,
            start_date,
            end_date,
            len(daily_reports),
        )

        # Store the progress analysis in MongoDB
        analysis_doc = {
            "analysis_id": str(uuid4()),
            "enrollment_id": str(enrollment_id),
            "patient_id": enrollment.get("patient_id"),
            "analysis_type": "progress_analysis",
            "start_date": start_date,
            "end_date": end_date,
            "analysis_content": ai_response.get("content", ""),
            "structured_analysis": analysis,
            "context_data": {
                "daily_reports_count": len(daily_reports),
                "has_inbody_report": latest_report is not None,
                "target_weight": enrollment.get("target_weight_kg"),
                "target_bmi": enrollment.get("target_bmi"),
            },
            "metadata": ai_response.get("metadata", {}),
            "created_at": datetime.now(),
        }

        await self.progress_analyses_collection.insert_one(analysis_doc)
        analysis["analysis_id"] = analysis_doc["analysis_id"]

        return analysis

    async def get_weight_loss_progress_data(
        self,
        enrollment_id: UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        """Get comprehensive weight loss progress data - MongoDB"""

        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        # Get enrollment from MongoDB
        enrollment = await self.enrollments_collection.find_one(
            {"enrollment_id": str(enrollment_id)}
        )

        if not enrollment:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Enrollment not found",
            )

        # Get patient info from PostgreSQL
        async with self.postgres_store.get_session() as session:
            patient = await session.get(
                Patient, UUID(enrollment["patient_id"])
            )

        # Get daily reports
        daily_reports = await self.get_daily_reports_data(
            UUID(enrollment["patient_id"]), start_date, end_date
        )

        # Get latest inbody report from MongoDB
        latest_report_cursor = (
            self.reports_collection.find({"enrollment_id": str(enrollment_id)})
            .sort("report_date", -1)
            .limit(1)
        )

        latest_report = None
        async for report in latest_report_cursor:
            latest_report = report
            break

        latest_report_summary = None
        if latest_report:
            latest_report_summary = {
                "report_id": latest_report.get("report_id"),
                "report_date": (
                    latest_report.get("report_date").isoformat()
                    if latest_report.get("report_date")
                    else None
                ),
                "processed": latest_report.get("processed", False),
                "extraction_confidence": latest_report.get(
                    "extraction_confidence"
                ),
                "abnormal_indicators_count": len(
                    [
                        h
                        for h in latest_report.get("health_indicators", [])
                        if h.get("is_abnormal")
                    ]
                ),
                "measurements_count": len(
                    latest_report.get("measurements", [])
                ),
            }

        return {
            "enrollment_id": str(enrollment_id),
            "patient_id": enrollment.get("patient_id"),
            "patient_name": (
                f"{patient.first_name} {patient.last_name}"
                if patient
                else "Unknown"
            ),
            "enrollment_date": (
                enrollment.get("enrollment_date").isoformat()
                if enrollment.get("enrollment_date")
                else None
            ),
            "is_active": enrollment.get("is_active", True),
            "target_weight_kg": enrollment.get("target_weight_kg"),
            "target_bmi": enrollment.get("target_bmi"),
            "latest_inbody_report": latest_report_summary,
            "daily_reports": daily_reports,
            "program_goals": enrollment.get("program_goals"),
        }

    def _is_value_abnormal(
        self, value: float, normal_min: float, normal_max: float
    ) -> bool:
        """Check if a value is outside normal range"""

        return value < normal_min or value > normal_max

    async def _get_fitness_data_for_date(
        self, patient_id: UUID, date: date
    ) -> Optional[Dict]:
        """Get fitness data for a specific date from ClickHouse"""

        try:
            # Format date for ClickHouse query
            start_datetime = f"{date.isoformat()} 00:00:00"
            end_datetime = f"{date.isoformat()} 23:59:59"

            # Query to get fitness data for the specific date
            query = f"""
            SELECT
                SUM(CASE WHEN type = 'STEPS' THEN value ELSE 0 END) AS total_steps,
                SUM(CASE WHEN type = 'ACTIVE_ENERGY_BURNED' THEN value ELSE 0 END) AS total_active_energy,
                SUM(dateDiff('minute', start_datetime, end_datetime)) AS total_active_duration
            FROM
                aihealth.fitness_data
            WHERE
                patient_id = '{str(patient_id)}'
                AND start_datetime >= '{start_datetime}'
                AND end_datetime <= '{end_datetime}'
            """

            result = self.clickhouse_store.client.execute(query)

            if result and len(result) > 0:
                steps, active_energy, active_duration = result[0]

                # Only return data if there's actual fitness data
                if steps > 0 or active_energy > 0 or active_duration > 0:
                    return {
                        "steps": int(steps) if steps else 0,
                        "active_energy": (
                            float(active_energy) if active_energy else 0.0
                        ),
                        "active_duration": (
                            int(active_duration) if active_duration else 0
                        ),
                    }

            # Return None if no data found
            return None

        except Exception as e:
            # Log error but don't fail the entire request
            print(
                f"Error fetching fitness data for {patient_id} on {date}: {str(e)}"
            )
            return None

    def _build_structured_analysis_prompt(
        self,
        enrollment: Dict,  # MongoDB document
        daily_reports: List[Dict],
        latest_report: Optional[Dict],  # MongoDB document
    ) -> str:
        """Build structured analysis prompt for AI that returns JSON format - MongoDB"""

        # Calculate age from date of birth
        age = None
        patient = enrollment.get("patient")
        if patient and hasattr(patient, "dob") and patient.dob:
            today = date.today()
            age = (
                today.year
                - patient.dob.year
                - (
                    (today.month, today.day)
                    < (patient.dob.month, patient.dob.day)
                )
            )

        prompt = f"""
You are a health and weight loss analysis AI. Analyze the following patient data and provide a structured JSON response.

Patient Information:
- Age: {age if age else 'Unknown'}
- Gender: {patient.gender if patient else 'Unknown'}
- Target Weight: {enrollment.get('target_weight_kg', 'Not set')} kg
- Target BMI: {enrollment.get('target_bmi', 'Not set')}
- Program Goals: {enrollment.get('program_goals') or 'Not specified'}
- Enrollment Date: {enrollment.get('enrollment_date').isoformat() if enrollment.get('enrollment_date') and hasattr(enrollment.get('enrollment_date'), 'isoformat') else str(enrollment.get('enrollment_date')) if enrollment.get('enrollment_date') else 'Unknown'}

Data Available:
- {len(daily_reports)} days of daily activity reports
"""

        # Add InBody report data if available
        if latest_report and latest_report.get("measurements"):
            measurements = latest_report.get("measurements", [])
            prompt += "\nLatest InBody Report Measurements:\n"
            for measurement in measurements[:10]:  # Limit to 10 measurements
                prompt += f"- {measurement.get('measurement_type')}: {measurement.get('value')} {measurement.get('unit')}\n"

            health_indicators = latest_report.get("health_indicators", [])
            if health_indicators:
                abnormal_count = len(
                    [h for h in health_indicators if h.get("is_abnormal")]
                )
                prompt += f"\nAbnormal Health Indicators: {abnormal_count}\n"

        # Add daily activity summary
        if daily_reports:
            prompt += "\nDaily Activity Summary (last 7 days):\n"
            for day in daily_reports[-7:]:
                prompt += f"\nDate: {day['date']}\n"

                if day.get("meal_data"):
                    meal_data = day["meal_data"]
                    prompt += f"  Meals: {meal_data.get('meals_count', 0)}, Total Calories: {meal_data.get('total_calories', 0)}\n"
                else:
                    prompt += "  No meal data\n"

                if day.get("fitness_data"):
                    fitness = day["fitness_data"]
                    prompt += f"  Steps: {fitness.get('steps', 0)}, Active Energy: {fitness.get('active_energy', 0)} kcal, Duration: {fitness.get('active_duration', 0)} min\n"
                else:
                    prompt += "  No fitness data\n"

                if day.get("vitals_data") and day["vitals_data"].get("weight"):
                    prompt += f"  Weight: {day['vitals_data']['weight']} kg\n"

        prompt += """

Please analyze this data and return ONLY a valid JSON object (no markdown, no extra text) with the following structure:
{
  "overall_health_score": <number between 0-100, or null if insufficient data>,
  "key_insights": [<array of 3-5 key insights as strings>],
  "recommendations": [<array of 3-5 actionable recommendations as strings>],
  "risk_factors": [<array of any identified risk factors as strings, empty array if none>],
  "progress_metrics": {
    "weight_trend": "<improving/stable/declining>",
    "activity_level": "<low/moderate/high>",
    "nutrition_adherence": "<poor/fair/good/excellent>",
    "days_with_data": <number>
  },
  "meal_analysis": {
    "average_daily_calories": <number or null>,
    "days_logged": <number>,
    "calorie_trend": "<increasing/stable/decreasing or null>",
    "summary": "<brief summary string>"
  },
  "fitness_analysis": {
    "average_daily_steps": <number or null>,
    "average_active_energy": <number or null>,
    "days_logged": <number>,
    "activity_trend": "<improving/stable/declining or null>",
    "summary": "<brief summary string>"
  },
  "vitals_analysis": {
    "weight_change": <number in kg or null>,
    "bmi_change": <number or null>,
    "days_logged": <number>,
    "trend": "<losing/maintaining/gaining or null>",
    "summary": "<brief summary string>"
  }
}

Important: Return ONLY the JSON object, no additional text or markdown formatting.
"""

        return prompt

    def _parse_analysis_response(
        self,
        ai_response: Dict,
        enrollment_id: UUID,
        start_date: datetime,
        end_date: datetime,
        daily_reports: List[Dict],
    ) -> Dict:
        """Parse AI response into structured analysis format"""

        import json

        # Extract the AI response content
        ai_content = ai_response.get("content", "")

        # Try to parse as JSON
        try:
            # Remove markdown code blocks if present
            if "```json" in ai_content:
                ai_content = (
                    ai_content.split("```json")[1].split("```")[0].strip()
                )
            elif "```" in ai_content:
                ai_content = ai_content.split("```")[1].split("```")[0].strip()

            # Parse JSON
            parsed_data = json.loads(ai_content)

            # Build the structured response
            return {
                "enrollment_id": str(enrollment_id),
                "analysis_period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
                "overall_health_score": parsed_data.get(
                    "overall_health_score"
                ),
                "key_insights": parsed_data.get("key_insights", []),
                "recommendations": parsed_data.get("recommendations", []),
                "risk_factors": parsed_data.get("risk_factors", []),
                "progress_metrics": parsed_data.get("progress_metrics", {}),
                "meal_analysis": parsed_data.get("meal_analysis"),
                "fitness_analysis": parsed_data.get("fitness_analysis"),
                "vitals_analysis": parsed_data.get("vitals_analysis"),
            }

        except (json.JSONDecodeError, KeyError, IndexError) as e:
            # Fallback: return empty structure if parsing fails
            print(f"Failed to parse AI analysis response: {str(e)}")
            print(
                f"AI Response content: {ai_content[:500]}"
            )  # Log first 500 chars

            # Calculate some basic metrics from daily_reports
            days_with_meals = len(
                [d for d in daily_reports if d.get("meal_data")]
            )
            days_with_fitness = len(
                [d for d in daily_reports if d.get("fitness_data")]
            )
            days_with_vitals = len(
                [d for d in daily_reports if d.get("vitals_data")]
            )

            return {
                "enrollment_id": str(enrollment_id),
                "analysis_period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                },
                "overall_health_score": None,
                "key_insights": [
                    f"Data available for {len(daily_reports)} days",
                    (
                        f"Meal data logged on {days_with_meals} days"
                        if days_with_meals > 0
                        else "No meal data available"
                    ),
                    (
                        f"Fitness data logged on {days_with_fitness} days"
                        if days_with_fitness > 0
                        else "No fitness data available"
                    ),
                ],
                "recommendations": [
                    "Upload more daily health data for better analysis",
                    "Ensure consistent logging of meals and fitness activities",
                ],
                "risk_factors": [],
                "progress_metrics": {
                    "days_with_data": len(daily_reports),
                    "days_with_meals": days_with_meals,
                    "days_with_fitness": days_with_fitness,
                    "days_with_vitals": days_with_vitals,
                },
                "meal_analysis": None,
                "fitness_analysis": None,
                "vitals_analysis": None,
            }

    async def chat_with_weight_loss_agent(
        self,
        enrollment_id: UUID,
        user_id: str,
        conversation_id: str,
        user_question: str,
    ) -> Dict:
        """Handle chatbot conversations about weight loss progress and reports - MongoDB"""

        # Get enrollment from MongoDB
        enrollment = await self.enrollments_collection.find_one(
            {"enrollment_id": str(enrollment_id)}
        )

        if not enrollment:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Enrollment not found",
            )

        # Get patient info from PostgreSQL
        async with self.postgres_store.get_session() as session:
            patient = await session.get(
                Patient, UUID(enrollment["patient_id"])
            )

        # Get recent daily reports (last 30 days)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        daily_reports = await self.get_daily_reports_data(
            UUID(enrollment["patient_id"]), start_date, end_date
        )

        # Get latest inbody report from MongoDB
        latest_report_cursor = (
            self.reports_collection.find({"enrollment_id": str(enrollment_id)})
            .sort("report_date", -1)
            .limit(1)
        )

        latest_report = None
        async for report in latest_report_cursor:
            latest_report = report
            break

        latest_report_summary = None
        if latest_report:
            measurements = latest_report.get("measurements", [])
            health_indicators = latest_report.get("health_indicators", [])

            latest_report_summary = {
                "report_id": latest_report.get("report_id"),
                "report_date": (
                    latest_report.get("report_date").isoformat()
                    if latest_report.get("report_date")
                    else None
                ),
                "processed": latest_report.get("processed", False),
                "measurements": [
                    {
                        "type": m.get("measurement_type"),
                        "value": m.get("value"),
                        "unit": m.get("unit"),
                        "normal_range": (
                            f"{m.get('normal_min')}-{m.get('normal_max')}"
                            if m.get("normal_min") and m.get("normal_max")
                            else None
                        ),
                    }
                    for m in measurements[
                        :10
                    ]  # Limit to first 10 measurements
                ],
                "health_indicators": [
                    {
                        "name": h.get("indicator_name"),
                        "abnormal": h.get("is_abnormal"),
                        "level": h.get("abnormality_level"),
                        "explanation": h.get("analysis_explanation"),
                    }
                    for h in health_indicators
                    if h.get("is_abnormal")
                ],
            }

        # Initialize AI conversation service
        ai_service = AiConversationService(
            conversation_type="weight-loss-agent",
            ai_model_provider="openai",
            selected_ai_model="gpt-4o",
        )

        # Create context with enrollment and report data
        enrollment_date = enrollment.get("enrollment_date")
        context_data = {
            "enrollment_info": {
                "target_weight": enrollment.get("target_weight_kg"),
                "target_bmi": enrollment.get("target_bmi"),
                "program_goals": enrollment.get("program_goals"),
                "enrollment_date": (
                    enrollment_date.isoformat() if enrollment_date else None
                ),
                "days_enrolled": (
                    (datetime.now() - enrollment_date).days
                    if enrollment_date
                    else None
                ),
            },
            "patient_info": {
                "age": (
                    (datetime.now().date() - patient.dob).days // 365
                    if patient and patient.dob
                    else None
                ),
                "gender": patient.gender if patient else None,
            },
            "recent_activity": (
                daily_reports[-7:] if daily_reports else []
            ),  # Last 7 days
            "latest_inbody_report": latest_report_summary,
            "question_type": "chatbot_conversation",
        }

        # Generate AI response
        ai_response = await ai_service.generate_response(
            patient_id=enrollment["patient_id"],
            user_id=user_id,
            conversation_id=conversation_id,
            human_input=user_question,
            conversation_type="weight-loss-agent",
            additional_context=context_data,
        )

        # Extract response - ai_response is message_data with 'content', not 'response'
        response_text = ai_response.get(
            "content",
            "I'm sorry, I couldn't generate a response at this time.",
        )
        metadata = ai_response.get("metadata", {})

        # Store the chat interaction in MongoDB
        interaction_doc = {
            "interaction_id": str(uuid4()),
            "enrollment_id": str(enrollment_id),
            "patient_id": enrollment["patient_id"],
            "user_id": user_id,
            "conversation_id": conversation_id,
            "interaction_type": "chat",
            "user_question": user_question,
            "ai_response": response_text,
            "context_used": {
                "has_recent_reports": len(daily_reports) > 0,
                "has_inbody_report": latest_report is not None,
                "days_of_data": len(daily_reports),
                "enrollment_days": (
                    (datetime.now() - enrollment_date).days
                    if enrollment_date
                    else None
                ),
            },
            "metadata": {
                "confidence_score": metadata.get("confidence_score"),
                "tags": metadata.get("tags", []),
                "citations": metadata.get("citations", []),
                "follow_up_questions": ai_response.get(
                    "follow_up_questions", []
                ),
            },
            "created_at": datetime.now(),
        }

        await self.interactions_collection.insert_one(interaction_doc)

        return {
            "response": response_text,
            "interaction_id": interaction_doc["interaction_id"],
            "confidence_score": metadata.get("confidence_score"),
            "tags": metadata.get("tags", []),
            "citations": metadata.get("citations", []),
            "follow_up_questions": ai_response.get("follow_up_questions", []),
            "context_used": interaction_doc["context_used"],
            "conversation_id": conversation_id,
        }

    async def process_and_analyze_inbody_report(
        self, enrollment_id: UUID, report_file, user_id: str
    ) -> InbodyReportAnalysisResult:
        """Process uploaded inbody report file with base64 conversion first, then get AI analysis - returns GPT response first, then stores data"""

        # WORKFLOW: Base64 First → AI Analysis → User Review → Database Storage
        try:
            # Step 1: Read file content and convert to base64 FIRST
            print("Step 1: Reading file content...")
            file_content = await report_file.read()
            file_name = report_file.filename
            content_type = report_file.content_type

            print(
                f"File details: {file_name}, type: {content_type}, size: {len(file_content)} bytes"
            )

            # Convert file content to base64 for AI processing
            print("Step 2: Converting file to base64...")
            import base64

            file_content_b64 = base64.b64encode(file_content).decode("utf-8")
            print(
                f"File successfully encoded to base64, length: {len(file_content_b64)} characters"
            )

            # Validate base64 conversion
            if not file_content_b64:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message="Failed to convert file to base64 format",
                )

            print("Step 3: Sending image to GPT-4 Vision for analysis...")

            # Use GPT-4 Vision for image analysis
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
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ]
                )

                # Get AI response
                ai_response_raw = await vision_model.ainvoke([message])
                ai_response_text = ai_response_raw.content

                print(
                    f"Vision analysis completed successfully. Response length: {len(ai_response_text)}"
                )

                # Parse the AI response to extract actual metric values
                confidence_score = 0.9  # Higher confidence for vision analysis
                extracted_metrics = {}
                recommendations = []
                risk_factors = []

                # Extract actual values using regex patterns
                import re

                # Weight extraction
                weight_match = re.search(
                    r"weight[:\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if weight_match:
                    extracted_metrics["weight"] = (
                        f"{weight_match.group(1)} {weight_match.group(2)}"
                    )

                # Target Weight extraction
                target_weight_match = re.search(
                    r"target\s+weight[:\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if target_weight_match:
                    extracted_metrics["target_weight"] = (
                        f"{target_weight_match.group(1)} {target_weight_match.group(2)}"
                    )

                # BMI extraction
                bmi_match = re.search(
                    r"bmi[:\s]+([\d.]+)", ai_response_text, re.IGNORECASE
                )
                if bmi_match:
                    extracted_metrics["bmi"] = bmi_match.group(1)

                # Body Fat Percentage extraction
                body_fat_match = re.search(
                    r"body fat[:\s]+([\d.]+)\s*%",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if body_fat_match:
                    extracted_metrics["body_fat_percentage"] = (
                        f"{body_fat_match.group(1)}%"
                    )

                # Skeletal Muscle Mass extraction
                muscle_match = re.search(
                    r"(?:skeletal\s+)?muscle mass[:\s]+([\d.]+)\s*(kg|lbs?|kilograms?|pounds?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if muscle_match:
                    extracted_metrics["muscle_mass"] = (
                        f"{muscle_match.group(1)} {muscle_match.group(2)}"
                    )

                # Body Water extraction
                water_match = re.search(
                    r"body water[:\s]+([\d.]+)\s*%",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if water_match:
                    extracted_metrics["body_water"] = (
                        f"{water_match.group(1)}%"
                    )

                # Visceral Fat Level extraction
                visceral_match = re.search(
                    r"visceral fat[:\s]+([\d.]+)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if visceral_match:
                    extracted_metrics["visceral_fat"] = visceral_match.group(1)

                # Basal Metabolic Rate extraction
                bmr_match = re.search(
                    r"(?:basal metabolic rate|bmr)[:\s]+([\d.]+)\s*(kcal|calories?)",
                    ai_response_text,
                    re.IGNORECASE,
                )
                if bmr_match:
                    extracted_metrics["basal_metabolic_rate"] = (
                        f"{bmr_match.group(1)} {bmr_match.group(2) if bmr_match.group(2) else 'kcal'}"
                    )

                # Calculate confidence score based on extracted metrics
                metric_count = len(extracted_metrics)
                if metric_count >= 5:
                    confidence_score = (
                        0.95  # High confidence with many metrics
                    )
                elif metric_count >= 3:
                    confidence_score = (
                        0.85  # Good confidence with several metrics
                    )
                elif metric_count >= 1:
                    confidence_score = (
                        0.7  # Moderate confidence with some metrics
                    )
                else:
                    confidence_score = (
                        0.5  # Low confidence with few or no metrics
                    )

                # Extract recommendations from the response
                if "recommend" in ai_response_text.lower():
                    # Try to extract specific recommendations
                    rec_patterns = [
                        r"recommendations?[:\s]*(.*?)(?:\n|$)",
                        r"priority recommendations?[:\s]*(.*?)(?:\n|$)",
                        r"strengths?[:\s]*(.*?)(?:\n|$)",
                        r"areas for improvement[:\s]*(.*?)(?:\n|$)",
                    ]
                    for pattern in rec_patterns:
                        rec_match = re.search(
                            pattern,
                            ai_response_text,
                            re.IGNORECASE | re.DOTALL,
                        )
                        if rec_match:
                            rec_text = rec_match.group(1).strip()
                            if (
                                rec_text and len(rec_text) > 10
                            ):  # Only add meaningful recommendations
                                recommendations.append(
                                    rec_text[:200]
                                )  # Limit length
                                break

                    if not recommendations:
                        recommendations.append(
                            "Follow the personalized recommendations provided in the analysis"
                        )

                # Extract risk factors
                if (
                    "risk" in ai_response_text.lower()
                    or "concern" in ai_response_text.lower()
                    or "abnormal" in ai_response_text.lower()
                ):
                    risk_patterns = [
                        r"risk factors?[:\s]*(.*?)(?:\n|$)",
                        r"concerns?[:\s]*(.*?)(?:\n|$)",
                        r"abnormal[:\s]*(.*?)(?:\n|$)",
                    ]
                    for pattern in risk_patterns:
                        risk_match = re.search(
                            pattern,
                            ai_response_text,
                            re.IGNORECASE | re.DOTALL,
                        )
                        if risk_match:
                            risk_text = risk_match.group(1).strip()
                            if risk_text and len(risk_text) > 10:
                                risk_factors.append(risk_text[:200])
                                break

                    if not risk_factors:
                        risk_factors.append(
                            "Review identified concerns with healthcare provider"
                        )

                ai_response = {
                    "response": ai_response_text,
                    "metadata": {
                        "confidence_score": confidence_score,
                        "extracted_metrics": extracted_metrics,
                        "recommendations": recommendations,
                        "risk_factors": risk_factors,
                    },
                }

            except Exception as ai_error:
                print(f"Vision analysis failed: {str(ai_error)}")
                # Provide fallback response
                ai_response = {
                    "response": f"File '{file_name}' has been uploaded successfully. AI vision analysis is currently unavailable, but the report has been stored for future processing.",
                    "metadata": {"confidence_score": 0.0},
                }

            normalized_payload = self._build_normalized_inbody_payload(
                ai_response.get("metadata", {}).get("extracted_metrics", {}),
                ai_response.get("metadata", {}).get("confidence_score", 0.0),
                file_name=file_name,
                content_type=content_type,
            )

            # Return AI response immediately without storing in database yet
            analysis_result = InbodyReportAnalysisResult(
                file_name=file_name,
                processed_at=datetime.now().isoformat(),
                ai_analysis={
                    "summary": ai_response.get(
                        "response",
                        "Analysis completed but no detailed response available.",
                    ),
                    "confidence_score": ai_response.get("metadata", {}).get(
                        "confidence_score", 0.0
                    ),
                    "extracted_metrics": ai_response.get("metadata", {}).get(
                        "extracted_metrics", {}
                    ),
                    "recommendations": ai_response.get("metadata", {}).get(
                        "recommendations", []
                    ),
                    "risk_factors": ai_response.get("metadata", {}).get(
                        "risk_factors", []
                    ),
                    "structured": (
                        True
                        if ai_response.get("metadata", {}).get(
                            "confidence_score", 0.0
                        )
                        > 0
                        else False
                    ),
                },
                values=normalized_payload["values"],
                derived=normalized_payload["derived"],
                parse_confidence=normalized_payload["parse_confidence"],
                confirmation_needed=normalized_payload["confirmation_needed"],
                provenance=normalized_payload["provenance"],
                metadata={
                    "content_type": content_type,
                    "file_size": len(file_content),
                    "enrollment_id": str(enrollment_id),
                    "original_filename": file_name,
                    "ready_for_storage": True,  # Flag indicating analysis is complete and ready to store
                },
            )

            print(
                f"Base64 processing workflow completed. Analysis result prepared with file: {analysis_result.file_name}"
            )

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
                    content_type=analysis_result.metadata.get(
                        "content_type", ""
                    ),
                )

                # Store the report in database
                report = await self.create_inbody_report(
                    enrollment_id, report_data
                )
                report_id = report["report_id"]
                print(f"Report stored in database with ID: {report_id}")

                # Step 6: Create measurements and health indicators from extracted metrics
                print(
                    "Step 6: Storing extracted measurements and health indicators..."
                )

                # Get extracted metrics from AI response
                extracted_metrics = analysis_result.ai_analysis.get(
                    "extracted_metrics", {}
                )
                confidence_score = analysis_result.ai_analysis.get(
                    "confidence_score", 0.0
                )

                # Create measurement documents
                measurements = []
                measurements_created = 0
                for metric_name, metric_value_str in extracted_metrics.items():
                    try:
                        # Parse the value and unit
                        import re

                        value_match = re.search(
                            r"([\d.]+)", str(metric_value_str)
                        )
                        if value_match:
                            value = float(value_match.group(1))

                            # Extract unit (everything after the number)
                            unit = (
                                str(metric_value_str)
                                .replace(value_match.group(1), "")
                                .strip()
                            )
                            if not unit:
                                # Default units based on metric type
                                if "weight" in metric_name.lower():
                                    unit = "kg"
                                elif "bmi" in metric_name.lower():
                                    unit = ""
                                elif (
                                    "fat" in metric_name.lower()
                                    or "water" in metric_name.lower()
                                ):
                                    unit = "%"
                                elif (
                                    "rate" in metric_name.lower()
                                    or "bmr" in metric_name.lower()
                                ):
                                    unit = "kcal"
                                else:
                                    unit = ""

                            # Create measurement document
                            measurement = {
                                "measurement_type": metric_name.replace(
                                    "_", " "
                                ).title(),
                                "value": value,
                                "unit": unit,
                                "confidence_score": confidence_score,
                            }
                            measurements.append(measurement)
                            measurements_created += 1
                            print(
                                f"  - Created measurement: {metric_name} = {value} {unit}"
                            )
                    except Exception as metric_error:
                        print(
                            f"  - Failed to create measurement for {metric_name}: {str(metric_error)}"
                        )

                # Create health indicators for abnormal values
                health_indicators = []
                indicators_created = 0

                # Check BMI (normal: 18.5-24.9)
                if "bmi" in extracted_metrics:
                    try:
                        bmi_str = extracted_metrics["bmi"]
                        value_match = re.search(r"([\d.]+)", str(bmi_str))
                        if value_match:
                            bmi_value = float(value_match.group(1))
                            if bmi_value >= 25:
                                indicator = {
                                    "indicator_name": (
                                        "Overweight BMI"
                                        if bmi_value < 30
                                        else "Obese BMI"
                                    ),
                                    "indicator_type": (
                                        "warning"
                                        if bmi_value < 30
                                        else "critical"
                                    ),
                                    "value": bmi_value,
                                    "unit": "",
                                    "is_abnormal": True,
                                    "abnormality_level": "high",
                                    "normal_range_min": 18.5,
                                    "normal_range_max": 24.9,
                                    "analysis_explanation": f"BMI of {bmi_value} indicates {'overweight' if bmi_value < 30 else 'obesity'} status, which may increase health risks.",
                                    "recommendations": "Consider a balanced diet and regular exercise to achieve healthy weight.",
                                }
                                health_indicators.append(indicator)
                                indicators_created += 1
                                print(
                                    f"  - Created indicator: Abnormal BMI ({bmi_value})"
                                )
                    except Exception as e:
                        print(f"  - Failed to process BMI indicator: {str(e)}")

                # Check Body Fat % (normal for women: 20-30%, men: 10-20%)
                if (
                    "body_fat_percentage" in extracted_metrics
                    or "body_fat" in extracted_metrics
                ):
                    try:
                        key = (
                            "body_fat_percentage"
                            if "body_fat_percentage" in extracted_metrics
                            else "body_fat"
                        )
                        bf_str = extracted_metrics[key]
                        value_match = re.search(r"([\d.]+)", str(bf_str))
                        if value_match:
                            bf_value = float(value_match.group(1))
                            if bf_value > 30:  # Using conservative threshold
                                indicator = {
                                    "indicator_name": "High Body Fat Percentage",
                                    "indicator_type": (
                                        "warning"
                                        if bf_value < 40
                                        else "critical"
                                    ),
                                    "value": bf_value,
                                    "unit": "%",
                                    "is_abnormal": True,
                                    "abnormality_level": "high",
                                    "normal_range_min": 20,
                                    "normal_range_max": 30,
                                    "analysis_explanation": f"Body fat percentage of {bf_value}% is above the healthy range, indicating excess body fat.",
                                    "recommendations": "Focus on fat reduction through cardio exercise and balanced nutrition.",
                                }
                                health_indicators.append(indicator)
                                indicators_created += 1
                                print(
                                    f"  - Created indicator: High Body Fat ({bf_value}%)"
                                )
                    except Exception as e:
                        print(
                            f"  - Failed to process body fat indicator: {str(e)}"
                        )

                # Check Visceral Fat (normal: 1-9)
                if "visceral_fat" in extracted_metrics:
                    try:
                        vf_str = extracted_metrics["visceral_fat"]
                        value_match = re.search(r"([\d.]+)", str(vf_str))
                        if value_match:
                            vf_value = float(value_match.group(1))
                            if vf_value >= 10:
                                indicator = {
                                    "indicator_name": "Elevated Visceral Fat",
                                    "indicator_type": (
                                        "warning"
                                        if vf_value < 15
                                        else "critical"
                                    ),
                                    "value": vf_value,
                                    "unit": "level",
                                    "is_abnormal": True,
                                    "abnormality_level": "high",
                                    "normal_range_min": 1,
                                    "normal_range_max": 9,
                                    "analysis_explanation": f"Visceral fat level of {vf_value} indicates increased health risks for metabolic and cardiovascular issues.",
                                    "recommendations": "Reduce visceral fat through aerobic exercise and limiting refined carbohydrates.",
                                }
                                health_indicators.append(indicator)
                                indicators_created += 1
                                print(
                                    f"  - Created indicator: Elevated Visceral Fat ({vf_value})"
                                )
                    except Exception as e:
                        print(
                            f"  - Failed to process visceral fat indicator: {str(e)}"
                        )

                # Update the report with measurements and indicators in MongoDB
                await self.reports_collection.update_one(
                    {"report_id": report_id},
                    {
                        "$set": {
                            "measurements": measurements,
                            "health_indicators": health_indicators,
                            "processed": True,  # Mark report as processed
                            "measurements_count": measurements_created,
                            "abnormal_indicators_count": indicators_created,
                            "extraction_confidence": confidence_score,
                            "updated_at": datetime.now(),
                        }
                    },
                )
                print(
                    f"Successfully stored {measurements_created} measurements and {indicators_created} health indicators"
                )

                # Update the analysis result with the report ID and storage info
                analysis_result.report_id = report_id
                analysis_result.stored_at = datetime.now().isoformat()
                analysis_result.metadata["stored"] = True
                analysis_result.metadata["measurements_created"] = (
                    measurements_created
                )
                analysis_result.metadata["indicators_created"] = (
                    indicators_created
                )
                analysis_result.metadata["ai_summary_pending"] = (
                    True  # Flag that AI summary needs to be stored later
                )

                print(
                    "Report successfully stored in database with measurements and health indicators"
                )
                return analysis_result

            except Exception as storage_error:
                print(
                    f"Failed to store report in database: {str(storage_error)}"
                )
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
                message=f"Failed to process inbody report: {str(e)}",
            )
