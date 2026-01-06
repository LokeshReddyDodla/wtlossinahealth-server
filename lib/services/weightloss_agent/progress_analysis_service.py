"""Progress analysis mixin for weight loss agent workflows."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import status

from lib.models.patient import Patient
from lib.models.weight_loss_agent import WeightLossAgentEnrollment
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.utils.http_exceptions import raise_http_exception


class ProgressAnalysisMixin:
    async def analyze_weight_loss_progress(
        self,
        enrollment_id: UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict:
        """Analyze weight loss progress using AI - PostgreSQL for enrollment"""

        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        # Get enrollment from PostgreSQL
        async with self.postgres_store.get_session() as session:
            enrollment_obj = await session.get(
                WeightLossAgentEnrollment, enrollment_id
            )

            if not enrollment_obj:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found",
                )

            # Get patient info
            patient = await session.get(Patient, enrollment_obj.patient_id)

            # Convert enrollment to dict for compatibility
            enrollment = self._serialize_enrollment(enrollment_obj)
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
            daily_reports,
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
        """Get comprehensive weight loss progress data - PostgreSQL for enrollment"""

        if not start_date:
            start_date = datetime.now() - timedelta(days=30)
        if not end_date:
            end_date = datetime.now()

        # Get enrollment from PostgreSQL
        async with self.postgres_store.get_session() as session:
            enrollment_obj = await session.get(
                WeightLossAgentEnrollment, enrollment_id
            )

            if not enrollment_obj:
                raise_http_exception(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message="Enrollment not found",
                )

            # Get patient info
            patient = await session.get(Patient, enrollment_obj.patient_id)

            # Convert enrollment to dict for compatibility
            enrollment = self._serialize_enrollment(enrollment_obj)

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
