"""Agentic chat orchestration for the weightloss program."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorCollection
from zoneinfo import ZoneInfo

from lib.core.constants import SYSTEM_USER_ID
from lib.core.mongo_store import MongoStore
from lib.schemas.chat import ChatSchema, ParticipantSchema
from lib.schemas.chat_message import ChatMessageCreate
from lib.schemas.weightloss_agent.coach import CoachActionRequest
from lib.schemas.weightloss_agent.plan import PlanGenerateRequest
from lib.services.chat.chat_messaging_service import ChatMessagingService
from lib.services.patient_profile_service import PatientProfileService
from lib.services.weight_loss_agent_service import WeightLossAgentService
from lib.services.weightloss_agent.coach_messenger_service import (
    CoachMessengerService,
)
from lib.services.weightloss_agent.flow_engine import FlowEngine
from lib.services.weightloss_agent.glp1_injection_service import (
    Glp1InjectionService,
)
from lib.services.weightloss_agent.glp1_symptoms_service import (
    Glp1SymptomsService,
)
from lib.services.weightloss_agent.holistic_summary_service import (
    HolisticSummaryService,
)
from lib.services.weightloss_agent.intake_service import IntakeService
from lib.services.weightloss_agent.plan_composer_service import (
    PlanComposerService,
)
from lib.services.weightloss_agent.safety_rules_service import (
    SafetyRulesService,
)
from lib.services.weightloss_agent.task_service import TaskService


@dataclass
class WorkoutWindow:
    start_local: time
    end_local: time


class AgenticChatService:
    WEIGHTLOSS_CHAT_DESCRIPTION = "weightloss_coach"
    WEIGHTLOSS_CHAT_NAME = "Weightloss Coach"
    DEFAULT_CHECKIN_TIME = "06:00"
    AFTERNOON_WALK_TIME = "14:00"
    END_OF_DAY_REVIEW_TIME = "21:00"
    DEFAULT_WORKOUT_START = "06:00"
    DEFAULT_WORKOUT_END = "06:30"
    FOLLOWUP1_OFFSET_MINUTES = 60
    FOLLOWUP2_TIME = "20:30"
    WORKOUT_CONFIRM_WINDOW_HOURS = 12
    WEEKLY_PROGRESS_DAY = 6  # 0=Monday .. 6=Sunday
    WEEKLY_PROGRESS_TIME = "19:00"
    GREETING_TERMS = {
        "hi",
        "hello",
        "hey",
        "hii",
        "yo",
        "morning",
        "afternoon",
        "evening",
    }

    def __init__(
        self,
        mongo_store: MongoStore,
        flow_engine: FlowEngine,
        task_service: TaskService,
        injection_service: Glp1InjectionService,
        intake_service: IntakeService,
        safety_rules_service: SafetyRulesService,
        chat_messaging_service: ChatMessagingService,
        plan_composer_service: PlanComposerService,
        weight_loss_agent_service: WeightLossAgentService,
        patient_profile_service: PatientProfileService,
        symptom_daily_collection: AsyncIOMotorCollection,
        glp1_symptoms_service: Glp1SymptomsService,
        coach_messenger_service: CoachMessengerService,
        suggestion_cards_collection: AsyncIOMotorCollection,
        holistic_summary_service: Optional[HolisticSummaryService] = None,
    ) -> None:
        self.mongo_store = mongo_store
        self.flow_engine = flow_engine
        self.task_service = task_service
        self.injection_service = injection_service
        self.intake_service = intake_service
        self.safety_rules_service = safety_rules_service
        self.chat_messaging_service = chat_messaging_service
        self.plan_composer_service = plan_composer_service
        self.weight_loss_agent_service = weight_loss_agent_service
        self.patient_profile_service = patient_profile_service
        self.symptom_daily_collection = symptom_daily_collection
        self.glp1_symptoms_service = glp1_symptoms_service
        self.coach_messenger_service = coach_messenger_service
        self.suggestion_cards_collection = suggestion_cards_collection
        self.holistic_summary_service = holistic_summary_service

    async def run_scheduled_for_user(self, user_id: UUID) -> None:
        now_utc = datetime.now(timezone.utc)
        await self.get_or_create_weightloss_chat_id(user_id)

        settings = await self.injection_service.get_settings(user_id)
        patient_locale = await self._get_patient_locale(user_id)
        timezone_name = self._resolve_timezone(settings, patient_locale)
        tz = ZoneInfo(timezone_name)
        now_local = now_utc.astimezone(tz)

        await self._maybe_run_daily_checkin(user_id, now_local, settings)
        await self._ensure_symptom_flow(user_id, now_local, settings)
        await self._maybe_run_weekly_progress(user_id, now_local)
        await self._maybe_regenerate_stale_plan(user_id)
        await self._maybe_deliver_coach_card(user_id, now_local)

        # Handle due flows for this user (workout follow-ups, symptoms, etc.)
        due_flows = await self.flow_engine.get_due_flows(user_id, now_utc)
        for flow in due_flows:
            flow_type = flow.get("flow_type")
            if flow_type == "workout_followup":
                await self._handle_workout_followup(flow, now_local)
            elif flow_type == "symptom_followup":
                await self._handle_symptom_followup(flow, now_local, settings)
            else:
                await self.flow_engine.complete_flow(flow.get("flow_id"))

        # Auto-complete steps if target is reached (runs on schedule)
        await self._auto_complete_steps(user_id, now_local)

    async def handle_user_message(
        self,
        user_id: UUID,
        message: str,
        *,
        enrollment_id: Optional[UUID] = None,
    ) -> Optional[str]:
        text = (message or "").strip().lower()
        if not text:
            return None

        now = datetime.now(timezone.utc)
        settings = await self.injection_service.get_settings(user_id)
        patient_locale = await self._get_patient_locale(user_id)
        timezone_name = self._resolve_timezone(settings, patient_locale)
        tz = ZoneInfo(timezone_name)
        now_local = now.astimezone(tz)
        today_str = now_local.date().isoformat()

        if await self._maybe_handle_workout_confirmation(
            user_id, today_str, text, now
        ):
            return None

        if await self._maybe_handle_symptom_response(user_id, text, now):
            return None

        if not enrollment_id:
            enrollment = (
                await self.weight_loss_agent_service.get_patient_enrollment_by_patient_id(
                    user_id
                )
            )
            if enrollment and enrollment.get("enrollment_id"):
                enrollment_id = UUID(enrollment["enrollment_id"])

        if enrollment_id:
            api_context = await self._build_chat_api_context(
                user_id=user_id,
                enrollment_id=enrollment_id,
                question=message,
                now_local=now_local,
            )
            if self._is_plain_greeting(text):
                greeting = self._build_data_driven_greeting(api_context)
                await self._send_bot_message(user_id, greeting)
                return greeting

            # --- Real-time safety gate ---
            safety_disclaimer = await self._evaluate_safety_gate(
                user_id, api_context
            )

            ai_response = await self.weight_loss_agent_service.chat_with_weight_loss_agent(
                enrollment_id=enrollment_id,
                user_id=str(user_id),
                conversation_id=f"agentic_{enrollment_id}",
                user_question=message,
                additional_context=api_context,
            )
            response_text = ai_response.get(
                "response",
                "Thanks for the update. Let me know if you want help with today's plan.",
            )
            if safety_disclaimer:
                response_text = f"{safety_disclaimer}\n\n{response_text}"
            await self._send_bot_message(user_id, response_text)
            return response_text

        await self._send_bot_message(
            user_id,
            "Thanks for the update. If you want to log a task, reply with 'done' "
            "or tell me what you completed.",
        )
        return None

    async def _build_chat_api_context(
        self,
        user_id: UUID,
        enrollment_id: UUID,
        question: str,
        now_local: datetime,
    ) -> Dict[str, Any]:
        """
        Build chat context by invoking the same service methods that back
        weightloss APIs (progress, inbody, intake, plan, safety, tasks).
        """

        context: Dict[str, Any] = {
            "api_calls": [],
            "question_focus": self._detect_question_focus(question),
            "response_contract": {
                "use_user_data": True,
                "be_specific": True,
                "avoid_generic_greetings": True,
                "coach_style": "weightloss_coach",
            },
        }

        def track(endpoint: str, ok: bool, detail: Optional[str] = None) -> None:
            payload: Dict[str, Any] = {"endpoint": endpoint, "ok": ok}
            if detail:
                payload["detail"] = detail
            context["api_calls"].append(payload)

        try:
            patient = await self.patient_profile_service.fetch_patient_profile(
                str(user_id)
            )
            context["patient_summary"] = {
                "patient_id": str(user_id),
                "first_name": patient.first_name if patient else None,
                "gender": patient.gender if patient else None,
            }
            track("/patient-profile/{patient_id}", True)
        except Exception as exc:  # pragma: no cover - defensive fallback
            track("/patient-profile/{patient_id}", False, str(exc))

        try:
            enrollment = await self.weight_loss_agent_service.get_patient_enrollment(
                enrollment_id
            )
            context["enrollment_snapshot"] = enrollment or {}
            track("/weight-loss-agent/enrollment/{enrollment_id}", True)
        except Exception as exc:
            track("/weight-loss-agent/enrollment/{enrollment_id}", False, str(exc))

        start_date = (now_local - timedelta(days=30)).replace(tzinfo=None)
        end_date = now_local.replace(tzinfo=None)
        try:
            progress = await self.weight_loss_agent_service.get_weight_loss_progress_data(
                enrollment_id, start_date, end_date
            )
            context["progress_snapshot"] = self._summarize_progress(progress)
            track("/weight-loss-agent/enrollment/{enrollment_id}/progress", True)
        except Exception as exc:
            track(
                "/weight-loss-agent/enrollment/{enrollment_id}/progress",
                False,
                str(exc),
            )

        if self._needs_analysis_snapshot(question):
            try:
                analysis = await self.weight_loss_agent_service.analyze_weight_loss_progress(
                    enrollment_id, start_date, end_date
                )
                context["analysis_snapshot"] = {
                    "overall_health_score": analysis.get("overall_health_score"),
                    "key_insights": analysis.get("key_insights", [])[:4],
                    "recommendations": analysis.get("recommendations", [])[:4],
                    "risk_factors": analysis.get("risk_factors", [])[:4],
                }
                track("/weight-loss-agent/enrollment/{enrollment_id}/analyze", True)
            except Exception as exc:
                track(
                    "/weight-loss-agent/enrollment/{enrollment_id}/analyze",
                    False,
                    str(exc),
                )

        try:
            latest_inbody = (
                await self.weight_loss_agent_service.get_latest_inbody_report_with_details(
                    enrollment_id
                )
            )
            context["latest_inbody_snapshot"] = (
                latest_inbody if latest_inbody else None
            )
            track("/weight-loss-agent/enrollment/{enrollment_id}/inbody-report", True)
        except Exception as exc:
            track(
                "/weight-loss-agent/enrollment/{enrollment_id}/inbody-report",
                False,
                str(exc),
            )

        try:
            reports_cursor = (
                self.weight_loss_agent_service.reports_collection.find(
                    {"enrollment_id": str(enrollment_id)}
                )
                .sort("report_date", -1)
                .limit(3)
            )
            reports = await reports_cursor.to_list(length=3)
            inbody_reports = [
                {
                    "report_id": report.get("report_id"),
                    "report_date": report.get("report_date").isoformat()
                    if isinstance(report.get("report_date"), datetime)
                    else report.get("report_date"),
                    "abnormal_indicators_count": len(
                        [
                            indicator
                            for indicator in (report.get("health_indicators") or [])
                            if indicator.get("is_abnormal")
                        ]
                    ),
                }
                for report in reports
            ]
            context["inbody_reports_snapshot"] = inbody_reports
            track("/weight-loss-agent/enrollment/{enrollment_id}/inbody-reports", True)

            if reports:
                latest_indicators = reports[0].get("health_indicators") or []
                context["latest_health_indicators"] = latest_indicators[:8]
                track(
                    "/weight-loss-agent/enrollment/{enrollment_id}/inbody-report/{report_id}/health-indicators",
                    True,
                )
        except Exception as exc:
            track(
                "/weight-loss-agent/enrollment/{enrollment_id}/inbody-reports",
                False,
                str(exc),
            )

        try:
            exercise = await self.intake_service.get_latest_exercise_preferences(
                user_id
            )
            fitness = await self.intake_service.get_latest_fitness_screen(user_id)
            willingness = await self.intake_service.get_latest_willingness(user_id)
            context["intake_snapshot"] = {
                "exercise_preferences": exercise or {},
                "fitness_screen": fitness or {},
                "willingness_commitment": willingness or {},
            }
            track("/intake/latest/exercise-preferences/{patient_id}", True)
            track("/intake/latest/fitness-screen/{patient_id}", True)
            track("/intake/latest/willingness-commitment/{patient_id}", True)
        except Exception as exc:
            track("/intake/latest/*/{patient_id}", False, str(exc))

        try:
            plan_details = await self.plan_composer_service.get_current_plan_details(
                user_id
            )
            context["plan_snapshot"] = self._summarize_plan(plan_details, now_local)
            track("/plan/current", True)
        except Exception as exc:
            track("/plan/current", False, str(exc))

        try:
            stored_context = await self.plan_composer_service.get_context_snapshot(
                user_id
            )
            safety_result = await self.safety_rules_service.evaluate(
                {
                    "user_id": str(user_id),
                    "medications": [],
                    "conditions": (stored_context or {}).get("conditions", {}),
                    "inbody": (stored_context or {}).get("inbody", {}),
                    "fitness": (stored_context or {}).get("fitness", {}),
                    "willingness": (stored_context or {}).get("willingness", {}),
                }
            )
            context["safety_snapshot"] = {
                "contraindications": safety_result.get("contraindications", []),
                "intensity_caps": safety_result.get("intensity_caps", []),
                "rationale_ids": safety_result.get("rationale_ids", []),
            }
            track("/safety/validate", True)
        except Exception as exc:
            track("/safety/validate", False, str(exc))

        try:
            today_str = now_local.date().isoformat()
            task_docs = await self.task_service.tasks_collection.find(
                {"user_id": str(user_id), "date": today_str}
            ).to_list(length=20)
            context["today_task_snapshot"] = [
                {
                    "task_id": task.get("task_id"),
                    "task_type": task.get("task_type"),
                    "status": task.get("status"),
                    "target_value": task.get("target_value"),
                    "metadata": task.get("metadata", {}),
                }
                for task in task_docs
            ]
            track("/weight-loss-agent/tasks/today", True)
        except Exception as exc:
            track("/weight-loss-agent/tasks/today", False, str(exc))

        try:
            settings = await self.injection_service.get_settings(user_id)
            context["glp_injection_settings"] = {
                "injection_date": (settings or {}).get("injection_date"),
                "injection_frequency_days": (
                    settings or {}
                ).get("injection_frequency_days"),
                "daily_checkin_time": (settings or {}).get("daily_checkin_time"),
                "timezone": (settings or {}).get("timezone"),
            }
            track("/weight-loss-agent/glp-injection", True)
        except Exception as exc:
            track("/weight-loss-agent/glp-injection", False, str(exc))

        try:
            symptoms = await self.symptom_daily_collection.find(
                {"user_id": str(user_id)}
            ).sort("captured_at", -1).limit(4).to_list(length=4)
            context["symptom_snapshot"] = [
                {
                    "captured_at": symptom.get("captured_at").isoformat()
                    if isinstance(symptom.get("captured_at"), datetime)
                    else symptom.get("captured_at"),
                    "severity": symptom.get("severity"),
                    "cadence": symptom.get("cadence"),
                    "notes": symptom.get("notes"),
                }
                for symptom in symptoms
            ]
            track("/weight-loss-agent/symptoms/recent", True)
        except Exception as exc:
            track("/weight-loss-agent/symptoms/recent", False, str(exc))

        try:
            daily_flow = await self.flow_engine.get_flow(user_id, "daily_checkin")
            flow_state = (daily_flow or {}).get("state_data", {})
            if flow_state.get("last_day_summary_text"):
                context["previous_day_summary"] = {
                    "date": flow_state.get("last_day_summary_date"),
                    "summary": flow_state.get("last_day_summary_text"),
                }
                track("/weight-loss-agent/daily-summary/context", True)
        except Exception as exc:
            track("/weight-loss-agent/daily-summary/context", False, str(exc))

        # Recent coaching suggestion cards
        try:
            recent_cards = await self._get_recent_coach_cards(user_id, limit=6)
            if recent_cards:
                context["coach_cards_snapshot"] = recent_cards
            track("/coach/recent-cards", True)
        except Exception as exc:
            track("/coach/recent-cards", False, str(exc))

        # Task completion streaks (last 7 days)
        try:
            streak_info = await self._compute_task_streak(user_id, now_local)
            if streak_info:
                context["task_streak_snapshot"] = streak_info
            track("/weight-loss-agent/tasks/streak", True)
        except Exception as exc:
            track("/weight-loss-agent/tasks/streak", False, str(exc))

        return context

    def _summarize_progress(self, progress_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        progress = progress_data or {}
        daily_reports = progress.get("daily_reports") or []
        last_week = daily_reports[-7:]

        step_values = []
        latest_weight = None
        for day in last_week:
            fitness = day.get("fitness_data") or {}
            steps = fitness.get("steps")
            if isinstance(steps, (int, float)):
                step_values.append(float(steps))

            vitals = day.get("vitals_data") or {}
            weight = vitals.get("weight")
            if isinstance(weight, (int, float)):
                latest_weight = float(weight)

        avg_steps = int(sum(step_values) / len(step_values)) if step_values else None

        return {
            "enrollment_date": progress.get("enrollment_date"),
            "is_active": progress.get("is_active"),
            "target_weight_kg": progress.get("target_weight_kg"),
            "target_bmi": progress.get("target_bmi"),
            "days_of_data": len(daily_reports),
            "average_steps_last_7_days": avg_steps,
            "latest_weight_kg": latest_weight,
            "recent_daily_reports": last_week,
            "latest_inbody_report": progress.get("latest_inbody_report"),
            "program_goals": progress.get("program_goals"),
        }

    def _summarize_plan(
        self, plan_details: Optional[Dict[str, Any]], now_local: datetime
    ) -> Dict[str, Any]:
        if not plan_details:
            return {}
        plan_snapshot = plan_details.get("plan_snapshot")
        ai_recommendations = plan_details.get("ai_recommendations") or {}
        timeline = ai_recommendations.get("timeline") or []
        today_name = now_local.strftime("%A")
        today_entry = next(
            (entry for entry in timeline if entry.get("day") == today_name), None
        )

        targets = {}
        if plan_snapshot and getattr(plan_snapshot, "targets", None):
            for key, value in (plan_snapshot.targets or {}).items():
                targets[key] = {
                    "label": value.label,
                    "min_value": value.min_value,
                    "max_value": value.max_value,
                    "units": value.units,
                    "cadence": value.cadence,
                }

        return {
            "plan_id": str(plan_snapshot.plan_id)
            if plan_snapshot and getattr(plan_snapshot, "plan_id", None)
            else None,
            "generated_at": plan_snapshot.generated_at.isoformat()
            if plan_snapshot and getattr(plan_snapshot, "generated_at", None)
            else None,
            "targets": targets,
            "today_timeline": today_entry,
            "suggestions": ai_recommendations.get("suggestions", []),
        }

    def _detect_question_focus(self, question: str) -> Dict[str, bool]:
        text = (question or "").lower()
        return {
            "needs_progress": any(
                term in text for term in ("progress", "track", "weight", "steps")
            ),
            "needs_plan": any(
                term in text
                for term in ("plan", "workout", "exercise", "target")
            ),
            "needs_inbody": any(
                term in text
                for term in (
                    "inbody",
                    "body fat",
                    "muscle",
                    "visceral",
                    "indicator",
                )
            ),
            "needs_symptoms": any(
                term in text
                for term in ("symptom", "nausea", "injection", "glp")
            ),
            "needs_safety": any(
                term in text for term in ("safe", "safety", "risk", "pain")
            ),
        }

    def _needs_analysis_snapshot(self, question: str) -> bool:
        text = (question or "").lower()
        return any(
            phrase in text
            for phrase in (
                "analysis",
                "insight",
                "recommendation",
                "why",
                "how am i doing",
            )
        )

    def _is_plain_greeting(self, text: str) -> bool:
        cleaned = re.sub(r"[^a-zA-Z\s]", " ", text).strip().lower()
        if not cleaned:
            return False
        tokens = [token for token in cleaned.split() if token]
        if cleaned in {"hi", "hello", "hey", "good morning", "good evening"}:
            return True
        return bool(tokens) and len(tokens) <= 3 and all(
            token in self.GREETING_TERMS for token in tokens
        )

    def _build_data_driven_greeting(self, context: Dict[str, Any]) -> str:
        patient_name = (
            ((context.get("patient_summary") or {}).get("first_name")) or "there"
        )
        progress = context.get("progress_snapshot") or {}
        avg_steps = progress.get("average_steps_last_7_days")
        latest_weight = progress.get("latest_weight_kg")

        tasks = context.get("today_task_snapshot") or []
        pending_workout = next(
            (
                task
                for task in tasks
                if task.get("task_type") == "workout"
                and task.get("status") == "pending"
            ),
            None,
        )
        steps_task = next(
            (
                task
                for task in tasks
                if task.get("task_type") == "steps"
            ),
            None,
        )

        parts = [f"Hi {patient_name}!"]
        if isinstance(avg_steps, int):
            parts.append(f"Your 7-day average is {avg_steps} steps.")
        if isinstance(latest_weight, (int, float)):
            parts.append(f"Latest logged weight: {latest_weight:.1f} kg.")
        if steps_task and steps_task.get("target_value"):
            parts.append(
                f"Today's steps target is {int(float(steps_task['target_value']))}."
            )
        has_workout_prompt = False
        if pending_workout:
            window_start = ((pending_workout.get("metadata") or {}).get("window_start"))
            window_end = ((pending_workout.get("metadata") or {}).get("window_end"))
            if window_start and window_end:
                parts.append(
                    f"You also have a workout planned for {window_start}-{window_end}."
                )
            else:
                parts.append("You also have a workout planned today.")
            has_workout_prompt = True

        if has_workout_prompt:
            parts.append("Did you complete today's workout?")
        else:
            parts.append("What would you like help with today: steps, meals, or plan?")
        return " ".join(parts)

    async def initialize_symptom_flow(self, user_id: UUID) -> None:
        settings = await self.injection_service.get_settings(user_id)
        if not settings or not settings.get("injection_date"):
            return
        flow = await self.flow_engine.get_or_create_flow(
            user_id,
            "symptom_followup",
            state_data={"awaiting_response": False},
        )
        await self.flow_engine.update_flow(
            flow["flow_id"],
            {
                "state_data": {
                    "awaiting_response": False,
                    "cadence": "daily",
                    "injection_date": settings.get("injection_date"),
                },
                "next_run_at": datetime.now(timezone.utc),
            },
        )

    async def get_or_create_weightloss_chat_id(self, user_id: UUID) -> str:
        chat = await self.mongo_store.db["chats"].find_one(
            {
                "description": self.WEIGHTLOSS_CHAT_DESCRIPTION,
                "participants.id": str(user_id),
            }
        )
        if chat:
            return str(chat["_id"])

        participant = ParticipantSchema(
            id=str(user_id),
            type="patient",
            is_read_only=False,
            is_muted=False,
            is_archived=False,
            is_pinned=False,
        )
        chat_schema = ChatSchema(
            is_group=True,
            alias_name=self.WEIGHTLOSS_CHAT_NAME,
            alias_profile_picture=None,
            description=self.WEIGHTLOSS_CHAT_DESCRIPTION,
            participants=[participant],
            unread_counts={str(user_id): 0},
        )
        chat_dict = chat_schema.model_dump(by_alias=True)
        await self.mongo_store.insert_document("chats", chat_dict)
        return chat_schema.id

    async def record_user_message(self, user_id: UUID, content: str) -> None:
        chat_id = await self.get_or_create_weightloss_chat_id(user_id)
        message = ChatMessageCreate(
            chat_id=str(chat_id),
            sender_id=str(user_id),
            content=content,
            media=None,
            reply_to=None,
            timestamp=datetime.now(timezone.utc),
            metadata={"type": "text", "status": "sent"},
            severity="low",
            is_flagged=False,
        )
        await self.chat_messaging_service.add_message(message)

    async def get_chat_history(
        self, user_id: UUID, *, limit: int = 200
    ) -> Dict[str, Any]:
        chat_id = await self.get_or_create_weightloss_chat_id(user_id)
        query_limit = max(1, min(limit, 500))
        cursor = (
            self.mongo_store.db["chat_messages"]
            .find({"chat_id": str(chat_id)})
            .sort("timestamp", 1)
            .limit(query_limit)
        )
        docs = await cursor.to_list(length=query_limit)

        messages = []
        for doc in docs:
            timestamp = doc.get("timestamp")
            updated_at = doc.get("updated_at")
            messages.append(
                {
                    "message_id": doc.get("_id"),
                    "chat_id": doc.get("chat_id"),
                    "sender_id": doc.get("sender_id"),
                    "sender_role": (
                        "coach"
                        if doc.get("sender_id") == str(SYSTEM_USER_ID)
                        else "user"
                    ),
                    "content": doc.get("content"),
                    "metadata": doc.get("metadata", {}),
                    "timestamp": (
                        timestamp.isoformat()
                        if isinstance(timestamp, datetime)
                        else timestamp
                    ),
                    "updated_at": (
                        updated_at.isoformat()
                        if isinstance(updated_at, datetime)
                        else updated_at
                    ),
                }
            )

        return {
            "chat_id": str(chat_id),
            "count": len(messages),
            "messages": messages,
        }

    async def _send_bot_message(self, user_id: UUID, content: str) -> None:
        chat_id = await self.get_or_create_weightloss_chat_id(user_id)
        message = ChatMessageCreate(
            chat_id=str(chat_id),
            sender_id=str(SYSTEM_USER_ID),
            content=content,
            media=None,
            reply_to=None,
            timestamp=datetime.now(timezone.utc),
            metadata={"type": "text", "status": "sent"},
            severity="low",
            is_flagged=False,
        )
        await self.chat_messaging_service.add_message(message)

    async def _maybe_run_daily_checkin(
        self,
        user_id: UUID,
        now_local: datetime,
        settings: Optional[Dict[str, Any]],
    ) -> None:
        flow = await self.flow_engine.get_or_create_flow(
            user_id,
            "daily_checkin",
            state_data={
                "last_morning_plan_date": None,
                "last_afternoon_walk_date": None,
                "last_end_of_day_review_date": None,
                "last_day_summary_date": None,
                "last_day_summary_text": None,
            },
        )
        state_data = dict(flow.get("state_data", {}) or {})

        morning_time = self._parse_time(self.DEFAULT_CHECKIN_TIME) or time(6, 0)
        afternoon_time = self._parse_time(self.AFTERNOON_WALK_TIME) or time(14, 0)
        end_of_day_time = self._parse_time(self.END_OF_DAY_REVIEW_TIME) or time(22, 0)

        today = now_local.date()
        today_str = today.isoformat()
        tzinfo = now_local.tzinfo

        morning_dt = datetime.combine(today, morning_time, tzinfo=tzinfo)
        afternoon_dt = datetime.combine(today, afternoon_time, tzinfo=tzinfo)
        end_of_day_dt = datetime.combine(today, end_of_day_time, tzinfo=tzinfo)

        if (
            state_data.get("last_morning_plan_date") != today_str
            and now_local >= morning_dt
        ):
            sent = await self._send_daily_checkin(
                user_id,
                now_local,
                previous_day_summary_text=state_data.get("last_day_summary_text"),
                previous_day_summary_date=state_data.get("last_day_summary_date"),
            )
            # Unsent (analysis still generating) stays unmarked so the next
            # scheduled run retries — delivered late rather than replaced.
            if sent:
                state_data["last_morning_plan_date"] = today_str

        if (
            state_data.get("last_afternoon_walk_date") != today_str
            and now_local >= afternoon_dt
        ):
            await self._send_after_meal_walk_nudge(user_id)
            state_data["last_afternoon_walk_date"] = today_str

        if (
            state_data.get("last_end_of_day_review_date") != today_str
            and now_local >= end_of_day_dt
        ):
            day_summary = await self._send_end_of_day_review(user_id, now_local)
            # None means the LLM review failed — leave the slot unmarked so
            # the next scheduled run retries instead of falling back to a
            # canned message.
            if day_summary:
                state_data["last_end_of_day_review_date"] = today_str
                state_data["last_day_summary_date"] = today_str
                state_data["last_day_summary_text"] = day_summary

        next_run_local = self._next_daily_checkpoint(
            now_local,
            morning_time=morning_time,
            afternoon_time=afternoon_time,
            end_of_day_time=end_of_day_time,
        )
        await self.flow_engine.update_flow(
            flow["flow_id"],
            {
                "state_data": state_data,
                "next_run_at": next_run_local.astimezone(timezone.utc),
            },
        )

    async def _ensure_symptom_flow(
        self,
        user_id: UUID,
        now_local: datetime,
        settings: Optional[Dict[str, Any]],
    ) -> None:
        if not settings or not settings.get("injection_date"):
            return
        flow = await self.flow_engine.get_or_create_flow(
            user_id,
            "symptom_followup",
            state_data={"awaiting_response": False},
        )
        if flow.get("next_run_at"):
            return
        await self.flow_engine.update_flow(
            flow["flow_id"], {"next_run_at": datetime.now(timezone.utc)}
        )

    async def _maybe_run_weekly_progress(
        self, user_id: UUID, now_local: datetime
    ) -> None:
        """Send an AI-generated weekly progress report on Sunday evening.

        Uses a ``weekly_progress`` flow to track state so the report is only
        sent once per week.  The flow's ``next_run_at`` is always advanced to
        the *next* Sunday at ``WEEKLY_PROGRESS_TIME`` after sending.
        """
        flow = await self.flow_engine.get_or_create_flow(
            user_id,
            "weekly_progress",
            state_data={"last_report_week": None},
        )
        state_data = dict(flow.get("state_data", {}) or {})

        progress_time = self._parse_time(self.WEEKLY_PROGRESS_TIME) or time(19, 0)
        today = now_local.date()
        today_weekday = today.weekday()  # 0=Monday .. 6=Sunday

        # Only fire on the configured day at or after the target time
        if today_weekday != self.WEEKLY_PROGRESS_DAY:
            # Advance next_run to the coming Sunday
            days_until = (self.WEEKLY_PROGRESS_DAY - today_weekday) % 7 or 7
            next_sunday = today + timedelta(days=days_until)
            next_run = datetime.combine(
                next_sunday, progress_time, tzinfo=now_local.tzinfo
            ).astimezone(timezone.utc)
            if flow.get("next_run_at") != next_run:
                await self.flow_engine.update_flow(
                    flow["flow_id"], {"next_run_at": next_run}
                )
            return

        target_dt = datetime.combine(today, progress_time, tzinfo=now_local.tzinfo)
        if now_local < target_dt:
            await self.flow_engine.update_flow(
                flow["flow_id"],
                {"next_run_at": target_dt.astimezone(timezone.utc)},
            )
            return

        # ISO week string to de-duplicate within the same calendar week
        week_key = today.isocalendar()
        week_str = f"{week_key[0]}-W{week_key[1]:02d}"
        if state_data.get("last_report_week") == week_str:
            # Already sent this week — schedule for next Sunday
            next_sunday = today + timedelta(days=7)
            next_run = datetime.combine(
                next_sunday, progress_time, tzinfo=now_local.tzinfo
            ).astimezone(timezone.utc)
            await self.flow_engine.update_flow(
                flow["flow_id"], {"next_run_at": next_run}
            )
            return

        # Resolve enrollment to call the progress analysis
        enrollment = (
            await self.weight_loss_agent_service.get_patient_enrollment_by_patient_id(
                user_id
            )
        )
        if not enrollment or not enrollment.get("enrollment_id"):
            return

        enrollment_id = UUID(enrollment["enrollment_id"])
        try:
            analysis = (
                await self.weight_loss_agent_service.analyze_weight_loss_progress(
                    enrollment_id=enrollment_id,
                    start_date=datetime.combine(
                        today - timedelta(days=7), datetime.min.time()
                    ),
                    end_date=datetime.combine(today, datetime.max.time()),
                )
            )
        except Exception:
            # If analysis fails, retry next tick
            return

        # Build a concise chat-friendly summary from the analysis dict
        summary_parts = ["📊 Weekly Progress Report"]
        if analysis.get("summary"):
            summary_parts.append(str(analysis["summary"]))
        if analysis.get("key_metrics"):
            metrics = analysis["key_metrics"]
            if isinstance(metrics, dict):
                for key, val in metrics.items():
                    label = key.replace("_", " ").title()
                    summary_parts.append(f"• {label}: {val}")
            elif isinstance(metrics, list):
                for item in metrics[:6]:
                    summary_parts.append(f"• {item}")
        if analysis.get("recommendations"):
            recs = analysis["recommendations"]
            if isinstance(recs, list):
                summary_parts.append("Recommendations:")
                for rec in recs[:3]:
                    summary_parts.append(f"  → {rec}")
            elif isinstance(recs, str):
                summary_parts.append(f"Recommendations: {recs}")
        summary_parts.append(
            "Keep going! Reply anytime if you want to dig deeper into your data."
        )

        await self._send_bot_message(user_id, "\n".join(summary_parts))

        # Update state and schedule next run
        state_data["last_report_week"] = week_str
        next_sunday = today + timedelta(days=7)
        next_run = datetime.combine(
            next_sunday, progress_time, tzinfo=now_local.tzinfo
        ).astimezone(timezone.utc)
        await self.flow_engine.update_flow(
            flow["flow_id"],
            {"state_data": state_data, "next_run_at": next_run},
        )

    async def _send_daily_checkin(
        self,
        user_id: UUID,
        now_local: datetime,
        *,
        previous_day_summary_text: Optional[str] = None,
        previous_day_summary_date: Optional[str] = None,
    ) -> bool:
        """Deliver the morning coach message built from yesterday's holistic
        analysis.

        Returns False (and sends nothing) while the analysis is not yet
        complete — there is intentionally no rule-based fallback, so the
        check-in stays pending and is retried on the next scheduled run.
        """

        yesterday = now_local.date() - timedelta(days=1)

        analysis_doc = None
        if self.holistic_summary_service:
            analysis_doc = await self.holistic_summary_service.get_daily_analysis(
                user_id, yesterday
            )

        if not analysis_doc or analysis_doc.get("status") != "complete":
            from loguru import logger

            logger.warning(
                "holistic: morning check-in blocked — analysis {} for "
                "patient={} date={}; queueing analysis",
                (analysis_doc or {}).get("status", "missing"),
                user_id,
                yesterday,
            )
            from lib.workers.arq.redis import enqueue_job

            await enqueue_job(
                "run_daily_holistic_analysis",
                str(user_id),
                yesterday.isoformat(),
                _job_id=f"holistic-daily-{user_id}-{yesterday.isoformat()}-checkin",
            )
            return False

        morning_message = (analysis_doc.get("analysis") or {}).get(
            "morning_message"
        )
        if not morning_message:
            return False

        # Refresh today's plan every morning so tasks are based on latest state.
        try:
            await self.plan_composer_service.generate_plan(
                PlanGenerateRequest(user_id=user_id)
            )
        except Exception:
            # Fallback to current persisted plan if generation fails.
            pass

        plan_details = await self.plan_composer_service.get_current_plan_details(
            user_id
        )

        plan_snapshot = (plan_details or {}).get("plan_snapshot")
        ai_recommendations = (plan_details or {}).get("ai_recommendations") or {}
        timeline = ai_recommendations.get("timeline") or []

        today_name = now_local.strftime("%A")
        today_entry = next(
            (item for item in timeline if item.get("day") == today_name), None
        )

        steps_target = None
        if plan_snapshot and getattr(plan_snapshot, "targets", None):
            steps_target = plan_snapshot.targets.get("daily_steps")

        await self._send_bot_message(user_id, morning_message)

        await self._create_daily_tasks(
            user_id, now_local.date(), steps_target, today_entry
        )
        if steps_target:
            target_value = steps_target.min_value or steps_target.max_value
            if target_value:
                await self._maybe_send_steps_nudge(
                    user_id,
                    int(target_value),
                    now_local.date() - timedelta(days=1),
                )
        return True

    async def _send_after_meal_walk_nudge(self, user_id: UUID) -> None:
        await self._send_bot_message(
            user_id,
            "Post-lunch nudge: take a 10-minute walk after your meal. "
            "It helps glucose control and keeps your daily activity on track.",
        )

    async def _send_end_of_day_review(
        self, user_id: UUID, now_local: datetime
    ) -> Optional[str]:
        """LLM-generated evening review of today's (partial) data.

        Returns the review's completion summary, or None when generation
        failed — in that case no message is sent and the caller leaves the
        slot unmarked so it retries (no rule-based fallback by design).
        """

        date_str = now_local.date().isoformat()
        await self._auto_complete_steps(user_id, now_local)

        if not self.holistic_summary_service:
            return None

        try:
            review = await self.holistic_summary_service.generate_evening_review(
                user_id, now_local.date()
            )
        except Exception as exc:
            from loguru import logger

            logger.error(
                "holistic: evening review failed patient={} date={}: {} — "
                "no message sent, will retry on next run",
                user_id,
                date_str,
                exc,
            )
            return None

        message = review.message

        task_docs = await self.task_service.tasks_collection.find(
            {"user_id": str(user_id), "date": date_str}
        ).to_list(length=50)
        workout_task = next(
            (task for task in task_docs if task.get("task_type") == "workout"),
            None,
        )
        if workout_task and workout_task.get("status") == "pending":
            await self.task_service.update_task_metadata(
                workout_task["task_id"],
                {
                    "last_prompted_at": datetime.now(timezone.utc).isoformat(),
                    "last_prompt_stage": "end_of_day_review",
                },
            )
            message = f"{message} Reply 'done' or 'not yet' for today's workout."

        await self._send_bot_message(user_id, message)
        return review.completion_summary

    def _next_daily_checkpoint(
        self,
        now_local: datetime,
        *,
        morning_time: time,
        afternoon_time: time,
        end_of_day_time: time,
    ) -> datetime:
        today = now_local.date()
        tzinfo = now_local.tzinfo
        checkpoints = [
            datetime.combine(today, morning_time, tzinfo=tzinfo),
            datetime.combine(today, afternoon_time, tzinfo=tzinfo),
            datetime.combine(today, end_of_day_time, tzinfo=tzinfo),
        ]
        future = [checkpoint for checkpoint in checkpoints if checkpoint > now_local]
        if future:
            return min(future)
        return datetime.combine(
            today + timedelta(days=1),
            morning_time,
            tzinfo=tzinfo,
        )

    async def _create_daily_tasks(
        self,
        user_id: UUID,
        day: date,
        steps_target: Any,
        today_entry: Optional[Dict[str, Any]],
    ) -> None:
        date_str = day.isoformat()
        if steps_target:
            target_value = steps_target.min_value or steps_target.max_value
            await self.task_service.get_or_create_task(
                user_id,
                "steps",
                date_str,
                target_value=target_value,
            )

        workout_day = bool(today_entry and today_entry.get("is_workout_day"))
        if not workout_day:
            return

        exercises = today_entry.get("exercises") if today_entry else []
        window = await self._resolve_workout_window(user_id, day)
        metadata = {
            "exercises": exercises or [],
            "window_start": window.start_local.strftime("%H:%M"),
            "window_end": window.end_local.strftime("%H:%M"),
        }
        workout_task = await self.task_service.get_or_create_task(
            user_id,
            "workout",
            date_str,
            metadata=metadata,
        )

        # Schedule follow-up prompts after the workout window
        if workout_task.get("status") == "pending":
            await self._schedule_workout_followups(
                user_id, workout_task, day, window
            )

    async def _schedule_workout_followups(
        self,
        user_id: UUID,
        task: Dict[str, Any],
        day: date,
        window: WorkoutWindow,
    ) -> None:
        settings = await self.injection_service.get_settings(user_id)
        patient_locale = await self._get_patient_locale(user_id)
        tz = ZoneInfo(self._resolve_timezone(settings, patient_locale))
        now_local = datetime.now(timezone.utc).astimezone(tz)

        end_dt_local = datetime.combine(day, window.end_local, tzinfo=tz)
        followup1_time = end_dt_local + timedelta(
            minutes=self.FOLLOWUP1_OFFSET_MINUTES
        )
        followup2_time_local = (
            self._parse_time(self.FOLLOWUP2_TIME) or time(20, 30)
        )
        followup2_time = datetime.combine(
            day, followup2_time_local, tzinfo=tz
        )
        if followup2_time <= followup1_time:
            followup2_time = min(
                followup1_time + timedelta(hours=4),
                datetime.combine(day, time(23, 0), tzinfo=tz),
            )

        if followup1_time <= now_local:
            followup1_time = now_local + timedelta(minutes=5)

        if followup1_time.date() == day:
            await self.flow_engine.create_flow(
                user_id,
                "workout_followup",
                state="scheduled",
                state_data={
                    "task_id": task["task_id"],
                    "followup_index": 1,
                    "date": day.isoformat(),
                },
                next_run_at=followup1_time.astimezone(timezone.utc),
            )

        if followup2_time > now_local:
            await self.flow_engine.create_flow(
                user_id,
                "workout_followup",
                state="scheduled",
                state_data={
                    "task_id": task["task_id"],
                    "followup_index": 2,
                    "date": day.isoformat(),
                },
                next_run_at=followup2_time.astimezone(timezone.utc),
            )

    async def _handle_workout_followup(
        self, flow: Dict[str, Any], now_local: datetime
    ) -> None:
        task_id = (flow.get("state_data") or {}).get("task_id")
        if not task_id:
            await self.flow_engine.complete_flow(flow.get("flow_id"))
            return

        task = await self.task_service.get_task_by_id(task_id)
        if not task or task.get("status") != "pending":
            await self.flow_engine.complete_flow(flow.get("flow_id"))
            return

        window_start = (task.get("metadata") or {}).get("window_start")
        window_end = (task.get("metadata") or {}).get("window_end")
        window_text = (
            f"{window_start}-{window_end}"
            if window_start and window_end
            else "today"
        )
        prompt = (
            f"Quick check-in: did you complete your workout scheduled for {window_text}? "
            "Reply 'done' or 'not yet'."
        )
        await self.task_service.update_task_metadata(
            task_id,
            {
                "last_prompted_at": datetime.now(timezone.utc).isoformat(),
                "last_prompt_stage": (flow.get("state_data") or {}).get(
                    "followup_index"
                ),
            },
        )
        await self._send_bot_message(UUID(task["user_id"]), prompt)
        await self.flow_engine.complete_flow(flow.get("flow_id"))

    async def _handle_symptom_followup(
        self,
        flow: Dict[str, Any],
        now_local: datetime,
        settings: Optional[Dict[str, Any]],
    ) -> None:
        user_id = UUID(flow["user_id"])
        if not settings or not settings.get("injection_date"):
            await self.flow_engine.complete_flow(flow.get("flow_id"))
            return

        injection_date = date.fromisoformat(settings["injection_date"])
        days_since = (now_local.date() - injection_date).days

        if days_since <= 0:
            next_time = self._parse_time(
                (settings or {}).get("daily_checkin_time")
                or self.DEFAULT_CHECKIN_TIME
            ) or time(9, 0)
            next_run = datetime.combine(
                injection_date + timedelta(days=1),
                next_time,
                tzinfo=now_local.tzinfo,
            ).astimezone(timezone.utc)
            await self.flow_engine.update_flow(
                flow["flow_id"],
                {
                    "state_data": {
                        "awaiting_response": False,
                        "cadence": "daily",
                        "injection_date": injection_date.isoformat(),
                    },
                    "next_run_at": next_run,
                },
            )
            return

        if 1 <= days_since <= 3:
            prompt = (
                "How are you feeling after your injection? "
                "Reply with none, mild, moderate, or severe (and optional notes)."
            )
            await self._send_bot_message(user_id, prompt)
            await self.flow_engine.update_flow(
                flow["flow_id"],
                {
                    "state_data": {
                        "awaiting_response": True,
                        "awaiting_until": (
                            datetime.now(timezone.utc)
                            + timedelta(hours=24)
                        ).isoformat(),
                        "cadence": "daily",
                        "injection_date": injection_date.isoformat(),
                    },
                    "next_run_at": (
                        datetime.combine(
                            now_local.date() + timedelta(days=1),
                            self._parse_time(
                                (settings or {}).get("daily_checkin_time")
                                or self.DEFAULT_CHECKIN_TIME
                            )
                            or time(9, 0),
                            tzinfo=now_local.tzinfo,
                        ).astimezone(timezone.utc)
                    ),
                },
            )
            return

        # Weekly follow-up after day 3
        prompt = (
            "Weekly check-in: how have your GLP-1 symptoms been this week? "
            "Reply none, mild, moderate, or severe (and optional notes)."
        )
        await self._send_bot_message(user_id, prompt)
        await self.flow_engine.update_flow(
            flow["flow_id"],
            {
                "state_data": {
                    "awaiting_response": True,
                    "awaiting_until": (
                        datetime.now(timezone.utc) + timedelta(days=3)
                    ).isoformat(),
                    "cadence": "weekly",
                    "injection_date": injection_date.isoformat(),
                },
                "next_run_at": (
                    datetime.combine(
                        now_local.date() + timedelta(days=7),
                        self._parse_time(
                            (settings or {}).get("daily_checkin_time")
                            or self.DEFAULT_CHECKIN_TIME
                        )
                        or time(9, 0),
                        tzinfo=now_local.tzinfo,
                    ).astimezone(timezone.utc)
                ),
            },
        )

    async def _auto_complete_steps(
        self, user_id: UUID, now_local: datetime
    ) -> None:
        date_str = now_local.date().isoformat()
        task = await self.task_service.get_pending_task(
            user_id, "steps", date_str
        )
        if not task or not task.get("target_value"):
            return

        start = datetime.combine(
            now_local.date(), datetime.min.time()
        ).replace(tzinfo=None)
        end = datetime.combine(
            now_local.date(), datetime.max.time()
        ).replace(tzinfo=None)

        daily_reports = await self.weight_loss_agent_service.get_daily_reports_data(
            user_id, start, end
        )
        steps = 0
        if daily_reports:
            fitness_data = daily_reports[-1].get("fitness_data") or {}
            steps = fitness_data.get("steps") or 0

        if steps >= float(task["target_value"]):
            await self.task_service.mark_task_done(
                task["task_id"], source="auto"
            )
            await self._send_bot_message(
                user_id,
                "Great job! You hit your step target, so I marked it done.",
            )

    async def _maybe_send_steps_nudge(
        self, user_id: UUID, target_steps: int, target_date: date
    ) -> None:
        start = datetime.combine(target_date, datetime.min.time()).replace(
            tzinfo=None
        )
        end = datetime.combine(target_date, datetime.max.time()).replace(
            tzinfo=None
        )
        daily_reports = await self.weight_loss_agent_service.get_daily_reports_data(
            user_id, start, end
        )
        if not daily_reports:
            return
        fitness_data = daily_reports[-1].get("fitness_data") or {}
        steps = fitness_data.get("steps") or 0
        if steps and steps < target_steps:
            await self._send_bot_message(
                user_id,
                f"I noticed your step count was low yesterday ({steps}). "
                f"Let’s aim for {target_steps} today to stay on track.",
            )

    async def _maybe_handle_workout_confirmation(
        self,
        user_id: UUID,
        date_str: str,
        text: str,
        now_utc: datetime,
    ) -> bool:
        task = await self.task_service.get_pending_task(
            user_id, "workout", date_str
        )
        if not task:
            return False

        last_prompted_at = (task.get("metadata") or {}).get("last_prompted_at")
        has_recent_prompt = False
        if last_prompted_at:
            try:
                last_prompt_dt = datetime.fromisoformat(last_prompted_at)
                if now_utc - last_prompt_dt > timedelta(
                    hours=self.WORKOUT_CONFIRM_WINDOW_HOURS
                ):
                    return False
                has_recent_prompt = True
            except ValueError:
                pass

        is_yes, is_no = self._parse_yes_no(text)
        if not is_yes and not is_no:
            return False

        if not has_recent_prompt and not self._mentions_workout(text):
            return False

        if is_yes:
            await self.task_service.mark_task_done(
                task["task_id"], source="manual"
            )
            await self._send_bot_message(
                user_id, "Awesome—workout marked as done."
            )
        else:
            await self.task_service.mark_task_skipped(
                task["task_id"], source="manual"
            )
            await self._send_bot_message(
                user_id,
                "Got it. We can adjust the plan or try a shorter session later.",
            )
        return True

    async def _maybe_handle_symptom_response(
        self, user_id: UUID, text: str, now_utc: datetime
    ) -> bool:
        # Don't intercept plain greetings as symptom responses
        if text.strip().lower() in self.GREETING_TERMS:
            return False

        flow = await self.flow_engine.get_flow(user_id, "symptom_followup")
        if not flow:
            return False
        state_data = flow.get("state_data") or {}
        if not state_data.get("awaiting_response"):
            return False

        awaiting_until = state_data.get("awaiting_until")
        if awaiting_until:
            try:
                if now_utc > datetime.fromisoformat(awaiting_until):
                    return False
            except ValueError:
                pass

        severity = self._parse_severity(text)
        await self.symptom_daily_collection.insert_one(
            {
                "user_id": str(user_id),
                "captured_at": now_utc,
                "severity": severity,
                "notes": text,
                "cadence": state_data.get("cadence"),
                "injection_date": state_data.get("injection_date"),
            }
        )
        await self.flow_engine.update_flow(
            flow["flow_id"],
            {
                "state_data": {
                    **state_data,
                    "awaiting_response": False,
                    "last_response_at": now_utc.isoformat(),
                }
            },
        )

        # Feed into clinical escalation pipeline on weekly cadence
        if state_data.get("cadence") == "weekly":
            await self._aggregate_weekly_symptoms(user_id, now_utc)

        await self._send_bot_message(
            user_id,
            "Thanks for sharing. I’ve logged your symptoms for follow-up.",
        )
        return True

    async def _aggregate_weekly_symptoms(
        self, user_id: UUID, now_utc: datetime
    ) -> None:
        """Aggregate the last 7 days of daily symptom entries into a
        Glp1SymptomsService.log_weekly_symptoms record so the clinical
        escalation pipeline can evaluate persistent severity and recurrent
        hypoglycemia.  This bridges chat-captured daily symptoms with the
        formal weekly symptom reporting required for safety monitoring.
        """
        from lib.schemas.weightloss_agent.symptoms import (
            SymptomEntry,
            WeeklySymptomsCreate,
        )

        week_end = now_utc.date()
        week_start = week_end - timedelta(days=6)

        cursor = self.symptom_daily_collection.find(
            {
                "user_id": str(user_id),
                "captured_at": {
                    "$gte": datetime.combine(
                        week_start, datetime.min.time(), tzinfo=timezone.utc
                    ),
                    "$lte": now_utc,
                },
            }
        )
        daily_docs = await cursor.to_list(length=100)
        if not daily_docs:
            return

        # Build a single aggregated SymptomEntry from daily severity reports.
        max_severity = max(doc.get("severity", 0) for doc in daily_docs)
        days_reported = len({
            doc["captured_at"].date()
            if isinstance(doc.get("captured_at"), datetime)
            else doc.get("captured_at")
            for doc in daily_docs
        })
        combined_notes = "; ".join(
            doc.get("notes", "") for doc in daily_docs if doc.get("notes")
        )

        # Pull medication info from injection settings
        settings = await self.injection_service.get_settings(user_id)
        medication_name = (settings or {}).get("medication_name")
        medication_dose_mg = (settings or {}).get("medication_dose_mg")

        payload = WeeklySymptomsCreate(
            user_id=user_id,
            medication_name=medication_name,
            medication_dose_mg=medication_dose_mg,
            week_start=week_start,
            week_end=week_end,
            symptoms=[
                SymptomEntry(
                    name="glp1_general",
                    severity_grade=max_severity,
                    days_reported=days_reported,
                    notes=combined_notes[:500] if combined_notes else None,
                )
            ],
            notes=f"Auto-aggregated from {len(daily_docs)} daily chat reports",
        )
        try:
            record = await self.glp1_symptoms_service.log_weekly_symptoms(payload)
            if record.escalation_triggered:
                await self._send_bot_message(
                    user_id,
                    "⚠️ Based on your recent symptom reports, I’ve flagged this "
                    "for your care provider’s review. Please reach out to your "
                    "doctor if symptoms worsen.",
                )
        except Exception:
            # Don't let aggregation failures break the chat flow
            pass

    # ------------------------------------------------------------------
    # Tier 2: Coach card delivery
    # ------------------------------------------------------------------
    async def _maybe_deliver_coach_card(
        self, user_id: UUID, now_local: datetime
    ) -> None:
        """Generate coaching cards via CoachMessengerService and send the
        highest-confidence card as a bot chat message.  Runs once per day
        (tracked via the daily_checkin flow's ``last_coach_card_date``).
        """
        flow = await self.flow_engine.get_flow(user_id, "daily_checkin")
        if not flow:
            return
        state_data = dict(flow.get("state_data", {}) or {})
        today_str = now_local.date().isoformat()

        if state_data.get("last_coach_card_date") == today_str:
            return  # Already delivered today

        try:
            response = await self.coach_messenger_service.act(
                CoachActionRequest(
                    user_id=user_id,
                    trigger="daily_scheduled",
                    context_tags=["agentic", "daily"],
                )
            )
        except Exception:
            return  # Don't block the pipeline if card generation fails

        if response.abstained or not response.cards:
            return

        # Pick the card with highest confidence
        best_card = max(response.cards, key=lambda c: c.confidence)
        card_message = f"💡 {best_card.title}\n{best_card.body}"
        if best_card.cta:
            card_message += f"\n👉 {best_card.cta}"
        await self._send_bot_message(user_id, card_message)

        state_data["last_coach_card_date"] = today_str
        await self.flow_engine.update_flow(
            flow["flow_id"], {"state_data": state_data}
        )

    # ------------------------------------------------------------------
    # Tier 2: Real-time safety gate
    # ------------------------------------------------------------------
    async def _evaluate_safety_gate(
        self, user_id: UUID, api_context: Dict[str, Any]
    ) -> Optional[str]:
        """Evaluate safety rules against current patient context.  Returns a
        disclaimer string if critical/high contraindications are triggered,
        otherwise ``None``.
        """
        safety_snapshot = api_context.get("safety_snapshot") or {}
        contraindications = safety_snapshot.get("contraindications") or []

        # Filter for critical and high severity only
        severe_flags = [
            c for c in contraindications
            if c.get("severity") in ("critical", "high")
        ]
        if not severe_flags:
            return None

        reasons = []
        for flag in severe_flags:
            desc = flag.get("description") or flag.get("type", "safety concern")
            reasons.append(f"• {desc} (severity: {flag.get('severity', 'high')})")

        disclaimer = (
            "⚠️ **Safety Notice** — Based on your health profile, the "
            "following precautions apply:\n"
            + "\n".join(reasons)
            + "\nPlease consult your care provider before making changes "
            "to your exercise or medication routine."
        )
        return disclaimer

    # ------------------------------------------------------------------
    # Tier 2: Auto-plan regeneration (staleness check)
    # ------------------------------------------------------------------
    PLAN_STALE_DAYS = 7

    async def _maybe_regenerate_stale_plan(self, user_id: UUID) -> None:
        """Regenerate the plan if it is older than ``PLAN_STALE_DAYS`` days.
        Runs once per day during the scheduled tick.  Uses the daily_checkin
        flow's ``last_plan_regen_date`` to de-duplicate.
        """
        flow = await self.flow_engine.get_flow(user_id, "daily_checkin")
        if not flow:
            return
        state_data = dict(flow.get("state_data", {}) or {})

        today_str = date.today().isoformat()
        if state_data.get("last_plan_regen_date") == today_str:
            return  # Already checked today

        plan = await self.plan_composer_service.get_current_plan(user_id)
        if plan:
            generated_at = plan.generated_at
            if isinstance(generated_at, str):
                try:
                    generated_at = datetime.fromisoformat(generated_at)
                except ValueError:
                    generated_at = None

            if generated_at:
                age_days = (datetime.now(timezone.utc) - generated_at.replace(
                    tzinfo=timezone.utc
                ) if generated_at.tzinfo is None else
                    datetime.now(timezone.utc) - generated_at).days
                if age_days < self.PLAN_STALE_DAYS:
                    state_data["last_plan_regen_date"] = today_str
                    await self.flow_engine.update_flow(
                        flow["flow_id"], {"state_data": state_data}
                    )
                    return

        # Plan is stale or missing — regenerate
        try:
            await self.plan_composer_service.generate_plan(
                PlanGenerateRequest(user_id=user_id)
            )
        except Exception:
            pass  # Will retry next tick

        state_data["last_plan_regen_date"] = today_str
        await self.flow_engine.update_flow(
            flow["flow_id"], {"state_data": state_data}
        )

    # ------------------------------------------------------------------
    # Tier 2: Enriched context helpers
    # ------------------------------------------------------------------
    async def _get_recent_coach_cards(
        self, user_id: UUID, *, limit: int = 6
    ) -> List[Dict[str, Any]]:
        """Fetch recent suggestion cards for the user from MongoDB."""
        cursor = (
            self.suggestion_cards_collection.find(
                {"user_id": str(user_id)},
                projection={
                    "_id": 0,
                    "title": 1,
                    "body": 1,
                    "card_type": 1,
                    "context_tags": 1,
                    "confidence": 1,
                    "created_at": 1,
                },
            )
            .sort("created_at", -1)
            .limit(limit)
        )
        results = await cursor.to_list(length=limit)
        return [
            {
                "card_type": item.get("card_type"),
                "title": item.get("title"),
                "body": item.get("body"),
                "context_tags": item.get("context_tags", []),
                "confidence": item.get("confidence"),
                "created_at": (
                    item["created_at"].isoformat()
                    if isinstance(item.get("created_at"), datetime)
                    else item.get("created_at")
                ),
            }
            for item in results
        ]

    async def _compute_task_streak(
        self, user_id: UUID, now_local: datetime
    ) -> Dict[str, Any]:
        """Compute a 7-day task completion summary for richer AI context."""
        today = now_local.date()
        dates = [(today - timedelta(days=i)).isoformat() for i in range(7)]
        cursor = self.task_service.tasks_collection.find(
            {"user_id": str(user_id), "date": {"$in": dates}}
        )
        tasks = await cursor.to_list(length=200)

        total = len(tasks)
        done = len([t for t in tasks if t.get("status") == "done"])
        skipped = len([t for t in tasks if t.get("status") == "skipped"])
        pending = len([t for t in tasks if t.get("status") == "pending"])

        # Compute consecutive days with all tasks completed (streak)
        streak = 0
        for i in range(7):
            day_str = (today - timedelta(days=i)).isoformat()
            day_tasks = [t for t in tasks if t.get("date") == day_str]
            if not day_tasks:
                break
            if all(t.get("status") == "done" for t in day_tasks):
                streak += 1
            else:
                break

        return {
            "period_days": 7,
            "total_tasks": total,
            "completed": done,
            "skipped": skipped,
            "pending": pending,
            "completion_rate": round(done / total, 2) if total else 0,
            "current_streak_days": streak,
        }

    async def _resolve_workout_window(
        self, user_id: UUID, day: date
    ) -> WorkoutWindow:
        context = await self.plan_composer_service.get_context_snapshot(
            user_id
        )
        preferences = (context or {}).get("exercise") or {}
        availability = preferences.get("availability") or []

        day_name = day.strftime("%A")
        slots = [
            slot
            for slot in availability
            if self._normalize_day(slot.get("day_of_week")) == day_name
        ]
        if slots:
            slots_sorted = sorted(
                slots,
                key=lambda s: s.get("start_local_time") or "",
            )
            start_time = self._parse_time(
                slots_sorted[0].get("start_local_time")
            )
            end_time = self._parse_time(
                slots_sorted[0].get("end_local_time")
            )
            if start_time and end_time:
                return WorkoutWindow(start_time, end_time)

        return WorkoutWindow(
            self._parse_time(self.DEFAULT_WORKOUT_START) or time(6, 0),
            self._parse_time(self.DEFAULT_WORKOUT_END) or time(6, 30),
        )

    async def _get_patient_locale(self, user_id: UUID) -> Optional[str]:
        patient = await self.patient_profile_service.fetch_patient_profile(
            str(user_id)
        )
        return patient.timezone if patient and patient.timezone else None

    def _resolve_timezone(
        self,
        settings: Optional[Dict[str, Any]],
        fallback_locale: Optional[str],
    ) -> str:
        tz = (settings or {}).get("timezone")
        if tz:
            return tz
        if fallback_locale:
            return fallback_locale
        return "Asia/Kolkata"

    def _parse_time(self, value: Optional[str]) -> Optional[time]:
        if not value or ":" not in value:
            return None
        try:
            parts = value.split(":")
            return time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None

    def _normalize_day(self, value: Optional[str]) -> str:
        if not value:
            return ""
        key = value.strip().lower()
        day_map = {
            "mon": "Monday",
            "monday": "Monday",
            "tue": "Tuesday",
            "tues": "Tuesday",
            "tuesday": "Tuesday",
            "wed": "Wednesday",
            "wednesday": "Wednesday",
            "thu": "Thursday",
            "thur": "Thursday",
            "thurs": "Thursday",
            "thursday": "Thursday",
            "fri": "Friday",
            "friday": "Friday",
            "sat": "Saturday",
            "saturday": "Saturday",
            "sun": "Sunday",
            "sunday": "Sunday",
        }
        return day_map.get(key, value.title())

    def _parse_yes_no(self, text: str) -> Tuple[bool, bool]:
        yes_terms = {"yes", "done", "completed", "did", "yep", "yeah"}
        no_terms = {"no", "not", "missed", "skip", "skipped", "didn't"}
        tokens = set(text.replace("'", "").split())
        return bool(tokens & yes_terms), bool(tokens & no_terms)

    def _mentions_workout(self, text: str) -> bool:
        normalized = text.lower()
        workout_terms = {
            "workout",
            "exercise",
            "training",
            "session",
            "gym",
            "cardio",
            "strength",
        }
        return any(term in normalized for term in workout_terms)

    def _parse_severity(self, text: str) -> int:
        if "severe" in text:
            return 3
        if "moderate" in text:
            return 2
        if "mild" in text:
            return 1
        if "none" in text or "no symptoms" in text or text.strip() == "no":
            return 0
        return 1
