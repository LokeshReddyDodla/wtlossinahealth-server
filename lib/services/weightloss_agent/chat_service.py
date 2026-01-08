"""Chat mixin for weight loss agent workflows."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict
from uuid import UUID, uuid4

from fastapi import status

from lib.models.patient import Patient
from lib.models.weight_loss_agent import WeightLossAgentEnrollment
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.utils.http_exceptions import raise_http_exception


class ChatMixin:
    async def chat_with_weight_loss_agent(
        self,
        enrollment_id: UUID,
        user_id: str,
        conversation_id: str,
        user_question: str,
    ) -> Dict:
        """Handle chatbot conversations about weight loss progress and reports - PostgreSQL for enrollment"""

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

            patient_id = enrollment_obj.patient_id

            # Convert enrollment to dict for compatibility
            enrollment = self._serialize_enrollment(enrollment_obj)

        # Get recent daily reports (last 30 days)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)

        daily_reports = await self.get_daily_reports_data(
            patient_id, start_date, end_date
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
                    for m in measurements[:10]
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
            api_endpoint="/weight-loss-agent/enrollment/{enrollment_id}/chat",
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
