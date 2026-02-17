import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from decouple import config
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from sqlalchemy import func, select

from lib.core.constants import ProfileTypeEnum
from lib.services.patient_summary.enum import StaleReason, SummaryState, RegeneratedBy
from lib.services.token_usage_service import TokenUsageService
from lib.services.patient_summary.models import InsightsResponse


class PatientSummaryService:
    SUMMARY_VERSION = "v1.0"
    MODEL_VERSION = "gpt-4o-mini"

    def __init__(
        self,
        patient_summary_collection,
        fitness_reports_collection,
        sleep_reports_collection,
        meal_reports_collection,
        cgm_reports_collection,
        token_usage_service: TokenUsageService,
    ):
        self.token_usage_service = token_usage_service

        # Mongo collections
        self.patient_summary_collection = patient_summary_collection
        self.fitness_reports_collection = fitness_reports_collection
        self.sleep_reports_collection = sleep_reports_collection
        self.meal_reports_collection = meal_reports_collection
        self.cgm_reports_collection = cgm_reports_collection

        self._llm: ChatOpenAI = ChatOpenAI(
            model=self.MODEL_VERSION,  # type: ignore
            temperature=0.4,
            api_key=SecretStr(str(config("OPENAI_API_KEY"))),
        )

    def _generate_report_id(
        self,
        patient_id: str,
        report_type: str,
        start_iso: str,
        end_iso: str,
    ) -> str:
        """Generate consistent report ID for patient summary."""
        key = f"{patient_id}_{report_type}_{start_iso}_{end_iso}"
        return hashlib.sha256(key.encode()).hexdigest()

    async def generate_daily_summary(
        self,
        patient_id: str,
        target_date: date,
        regenerated_by: RegeneratedBy = RegeneratedBy.SYSTEM,
        forced: bool = False,
    ) -> None:

        start_date = datetime.combine(
            target_date, datetime.min.time(), tzinfo=None
        )
        end_date = datetime.combine(
            target_date, datetime.max.time(), tzinfo=None
        )

        now = datetime.now()

        # Check if summary already exists
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        report_id = self._generate_report_id(
            patient_id, "daily", start_iso, end_iso
        )
        
        existing_summary = await self.patient_summary_collection.find_one(
            {"_id": report_id}
        )

        existing_meta = (existing_summary or {}).get("metadata", {})

        # 🚨 Guard: prevent regenerating finalized summaries unless forced
        if existing_summary and not forced:
            existing_state = existing_meta.get("state")
            if existing_state == SummaryState.FINALIZED.value:
                raise RuntimeError(
                    f"Cannot regenerate finalized summary for {patient_id} on {target_date}. "
                    "Set forced=True to override."
                )

        # 🚨 Guard: user can only generate if summary is STALE
        if regenerated_by == RegeneratedBy.USER:
            if not existing_meta:
                raise RuntimeError(
                    "User cannot generate summary before system job runs"
                )

            existing_state = existing_meta.get("state")
            if existing_state != SummaryState.STALE.value:
                raise RuntimeError(
                    f"Cannot regenerate summary from state '{existing_state}'"
                )

        # Build the summary snapshot
        summary = await self._build_summary_snapshot(
            patient_id, "daily", start_date, end_date
        )
        
        # Consolidate all metadata into single metadata object
        metadata = {
            # Report identification
            "report_type": "daily",
            "date_range": {
                "start": start_iso,
                "end": end_iso,
            },
            "summary_version": self.SUMMARY_VERSION,
            "model_version": self.MODEL_VERSION,
            
            # Lifecycle/state management
            "state": SummaryState.FINALIZED.value,
            "generated_at": now,
            "finalized_at": now if regenerated_by == RegeneratedBy.SYSTEM else None,
            "data_last_updated_at": existing_meta.get(
                "data_last_updated_at", now
            ),
            "regenerated_at": (
                now
                if regenerated_by == RegeneratedBy.USER
                else existing_meta.get("regenerated_at")
            ),
            "regenerated_by": regenerated_by.value,
            "stale_reason": (
                None
                if regenerated_by == RegeneratedBy.SYSTEM
                else existing_meta.get("stale_reason")
            ),
        }
        
        await self.patient_summary_collection.replace_one(
            {"_id": report_id},
            {
                "_id": report_id,
                "patient_id": patient_id,
                "created_at": existing_summary.get("created_at", now) if existing_summary else now,
                "updated_at": now,
                "metadata": metadata,
                **summary,
            },
            upsert=True,
        )

    async def _build_summary_snapshot(
        self,
        patient_id: str,
        period_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Dict[str, Any]:
        """
        Build a rich, per-period (typically daily) snapshot shaped roughly as:

        {
          "patient_id": "...",
          "data_presence": {...},
          "glucose": {...},
          "meals": {...},
          "activity": {...},
          "sleep": {...},
          "vitals": {...},
          "data_gaps": [...]
        }
        """

        period_date: date = end_date.date()

        glucose = await self._build_glucose_section(
            patient_id, start_date, end_date
        )
        meals = await self._build_meals_section(patient_id, period_date)
        activity = await self._build_activity_section(
            patient_id, start_date, end_date
        )
        sleep = await self._build_sleep_section(
            patient_id, start_date, end_date
        )
        vitals = await self._build_vitals_section(
            patient_id, start_date, end_date
        )

        data_presence = {
            "cgm": glucose is not None,
            "meals": meals is not None,
            "fitness": activity is not None,
            "sleep": sleep is not None,
            "vitals": vitals is not None,
        }

        data_gaps: List[str] = []
        flags: List[str] = []

        if not data_presence["cgm"]:
            data_gaps.append("No CGM data for period")
        if not data_presence["meals"]:
            data_gaps.append("No meals logged")
        if not data_presence["fitness"]:
            data_gaps.append("No activity data")
        if not data_presence["sleep"]:
            data_gaps.append("Sleep data missing")
        if not data_presence["vitals"]:
            data_gaps.append("No vitals recorded")

        # Insightful flags per domain (only check if data is present)
        if data_presence["cgm"] and glucose:
            if glucose.get("tir_pct") is not None and glucose["tir_pct"] < 70:
                flags.append("Low time-in-range (<70%)")
            if (
                glucose.get("avg_mgdl") is not None
                and glucose["avg_mgdl"] > 180
            ):
                flags.append("High average glucose (>180 mg/dL)")
            if (
                glucose.get("variability_pct") is not None
                and glucose["variability_pct"] > 36
            ):
                flags.append("High glucose variability (>36%)")
            if glucose.get("hyper_event_count", 0) > 0:
                flags.append("Hyperglycemia events detected")
            if glucose.get("hypo_event_count", 0) > 0:
                flags.append("Hypoglycemia events detected")

        if data_presence["meals"] and meals:
            if meals.get("meal_count", 0) < 2:
                flags.append("Low meal logging (<2 meals)")
                flags.append("Only one meal logged; comparison not available")
            best = meals.get("best_meal") or {}
            if best and best.get("score") is not None and best["score"] < 5:
                flags.append("No well-scored meals")
            totals = meals.get("nutrition_totals") or {}
            if (
                totals
                and totals.get("protein_g") is not None
                and totals["protein_g"] < 50
            ):
                flags.append("Low protein intake (<50g)")

        if data_presence["fitness"] and activity:
            if activity.get("steps", 0) < 3000:
                flags.append("Low steps (<3000)")
            if activity.get("active_minutes", 0) < 30:
                flags.append("Low active minutes (<30)")
            if activity.get("longest_inactive_minutes", 0) > 180:
                flags.append("Prolonged inactivity (>3h)")

        if data_presence["sleep"] and sleep:
            if (
                sleep.get("duration_hours") is not None
                and sleep["duration_hours"] < 6
            ):
                flags.append("Short sleep (<6h)")
            if (
                sleep.get("efficiency_pct") is not None
                and sleep["efficiency_pct"] < 75
            ):
                flags.append("Low sleep efficiency (<75%)")

        if data_presence["vitals"] and vitals:
            if vitals.get("blood_pressure_avg") is None:
                flags.append("No blood pressure data")
            if vitals.get("weight_kg") is None:
                flags.append("No weight data")

        return {
            "patient_id": patient_id,
            "data_presence": data_presence,
            "glucose": glucose,
            "meals": meals,
            "activity": activity,
            "sleep": sleep,
            "vitals": vitals,
            "data_gaps": data_gaps,
            "flags": flags,
            "insights": await self._build_insights(
                patient_id=patient_id,
                period_name=period_name,
                start_date=start_date,
                end_date=end_date,
                snapshot={
                    "glucose": glucose,
                    "meals": meals,
                    "activity": activity,
                    "sleep": sleep,
                    "vitals": vitals,
                    "data_presence": data_presence,
                    "flags": flags,
                    "data_gaps": data_gaps,
                },
            ),
        }

    # ------------------------------------------------------------------ #
    # Section builders
    # ------------------------------------------------------------------ #

    async def _build_glucose_section(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> Optional[Dict[str, Any]]:
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        
        doc = await self.cgm_reports_collection.find_one(
            {
                "patient_id": patient_id,
                "metadata.report_type": "daily",
                "metadata.date_range.start": {"$gte": start_iso, "$lte": end_iso},
            }
        )
        if not doc:
            return None

        summary = doc.get("cgm_summary_stats") or {}
        ranges = doc.get("cgm_range_stats") or {}
        hyper = (doc.get("hyper_stats") or {}) or {}
        hypo = (doc.get("hypo_stats") or {}) or {}
        periods = doc.get("time_period_stats") or {}

        # Derive TIR, above, below
        tir = ranges.get("in_target_70_180_percent", 0.0)
        below = (ranges.get("below_54_percent", 0.0)) + (
            ranges.get("below_70_above_54_percent", 0.0)
        )
        above = (ranges.get("above_180_below_250_percent", 0.0)) + (
            ranges.get("above_250_percent", 0.0)
        )

        best_period = None
        worst_period = None
        if isinstance(periods, dict) and periods:
            items = [
                (name, stats.get("average_glucose_mgdl", 0.0))
                for name, stats in periods.items()
                if isinstance(stats, dict)
            ]
            if items:
                best_period = max(items, key=lambda x: x[1])[0]
                worst_period = min(items, key=lambda x: x[1])[0]

        return {
            "avg_mgdl": summary.get("average_glucose_mgdl"),
            "tir_pct": tir,
            "above_range_pct": above,
            "below_range_pct": below,
            "gmi": summary.get("gmi"),
            "variability_pct": summary.get("glucose_variability_percent"),
            "hyper_event_count": hyper.get("hyper_events_count", 0),
            "hypo_event_count": hypo.get("hypo_events_count", 0),
            "best_period": best_period,
            "worst_period": worst_period,
        }

    async def _build_meals_section(
        self, patient_id: str, report_date: date
    ) -> Optional[Dict[str, Any]]:
        date_iso = report_date.isoformat()
        
        doc = await self.meal_reports_collection.find_one(
            {
                "patient_id": patient_id,
                "$or": [
                    {"date": date_iso},
                    {"metadata.date_range.start": {"$regex": f"^{date_iso}"}},
                ],
            }
        )
        if not doc:
            return None

        meals: List[Dict[str, Any]] = doc.get("meals", []) or []
        meal_count = doc.get("meal_count", 0)

        def _score(m: Dict[str, Any]) -> float:
            return float(m.get("score") or 0.0)

        best_meal = None
        worst_meal = None
        scored_meals = [m for m in meals if m.get("score") is not None]
        if scored_meals:
            best = max(scored_meals, key=_score)
            worst = min(scored_meals, key=_score)

            def _meal_view(m: Dict[str, Any]) -> Dict[str, Any]:
                macro = m.get("total_macro_nutritional_value", {}) or {}
                return {
                    "meal_id": (
                        str(m.get("id")) if m.get("id") is not None else None
                    ),
                    "name": m.get("name"),
                    "type": m.get("type"),
                    "score": m.get("score"),
                    "carbs_g": macro.get("carbohydrates"),
                    "tags": m.get("tags", []),
                    "image_url": m.get("image_url"),
                    "description": m.get("description"),
                }

            best_meal = _meal_view(best)
            # Avoid identical best/worst when only one scored meal
            worst_meal = (
                _meal_view(worst)
                if best is not worst and meal_count >= 2
                else None
            )

        nutrition_totals = {
            "calories": doc.get("calories"),
            "carbs_g": doc.get("carbohydrates"),
            "protein_g": doc.get("proteins"),
            "fat_g": doc.get("fats"),
            "fiber_g": doc.get("fiber"),
        }

        return {
            "meal_count": meal_count,
            "best_meal": best_meal,
            "worst_meal": worst_meal,
            "nutrition_totals": nutrition_totals,
            "notes": (
                ["Only one meal logged; comparison not available"]
                if meal_count < 2
                else []
            ),
        }

    async def _build_activity_section(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> Optional[Dict[str, Any]]:
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        
        doc = await self.fitness_reports_collection.find_one(
            {
                "patient_id": patient_id,
                "metadata.report_type": "daily",
                "metadata.date_range.start": {"$gte": start_iso, "$lte": end_iso},
            }
        )
        if not doc:
            return None

        inactive_periods: List[Dict[str, Any]] = (
            doc.get("inactive_periods", []) or []
        )
        longest_inactive = max(
            (p.get("inactive_duration", 0) for p in inactive_periods),
            default=0,
        )

        peak = doc.get("peak_activity_time") or {}

        steps_val = doc.get("steps")
        steps = steps_val if isinstance(steps_val, (int, float)) else 0
        # Return None if no meaningful activity data
        if not steps or steps == 0:
            return None

        return {
            "steps": steps,
            "active_minutes": doc.get("active_duration", 0),
            "longest_inactive_minutes": longest_inactive,
            "peak_activity_hour": peak.get("hour"),
        }

    async def _build_sleep_section(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> Optional[Dict[str, Any]]:
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        
        doc = await self.sleep_reports_collection.find_one(
            {
                "patient_id": patient_id,
                "metadata.report_type": "daily",
                "metadata.date_range.start": {"$gte": start_iso, "$lte": end_iso},
            }
        )
        if not doc:
            return None

        duration = doc.get("duration_analysis") or {}
        quality = doc.get("quality_analysis") or {}

        total_minutes = duration.get("total_duration") or 0
        duration_hours = round(total_minutes / 60, 1) if total_minutes else 0.0

        # Return None if no meaningful sleep data
        if duration_hours == 0.0:
            return None

        return {
            "duration_hours": duration_hours,
            "sleep_quality": quality.get("sleep_quality"),
            "efficiency_pct": quality.get("sleep_efficiency"),
        }

    async def _build_vitals_section(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> Optional[Dict[str, Any]]:
        """
        Aggregate vitals stored in Postgres for the given window.
        """
        from lib.core.container import container
        from lib.core.postgres_store import PostgresStore
        from lib.models.patient_vital import PatientVital

        store = container.resolve(PostgresStore)
        async with store.get_session() as session:
            result = await session.execute(
                select(
                    func.avg(PatientVital.weight),
                    func.avg(PatientVital.systolic_bp),
                    func.avg(PatientVital.diastolic_bp),
                    func.avg(PatientVital.heart_rate),
                    func.avg(PatientVital.spo2),
                    func.avg(PatientVital.temperature),
                    func.avg(PatientVital.respiratory_rate),
                    func.max(PatientVital.ketones),
                    func.max(PatientVital.a1c),
                ).where(
                    PatientVital.patient_id == patient_id,
                    PatientVital.test_time >= start_date.replace(tzinfo=None),
                    PatientVital.test_time <= end_date.replace(tzinfo=None),
                )
            )
            row = result.first()

        if not row:
            return None

        (
            weight,
            systolic,
            diastolic,
            heart_rate,
            spo2,
            temperature,
            respiratory_rate,
            ketones,
            a1c,
        ) = row

        if not any(
            [
                weight,
                systolic,
                diastolic,
                heart_rate,
                spo2,
                temperature,
                respiratory_rate,
                ketones,
                a1c,
            ]
        ):
            return None

        bp = None
        if systolic is not None or diastolic is not None:
            bp = {
                "systolic": systolic,
                "diastolic": diastolic,
            }

        return {
            "weight_kg": weight,
            "blood_pressure_avg": bp,
            "heart_rate_avg": heart_rate,
            "spo2_avg": spo2,
            "temperature_avg_c": temperature,
            "respiratory_rate_avg": respiratory_rate,
            "ketones_max": ketones,
            "a1c_latest": a1c,
        }

    # ------------------------------------------------------------------ #
    # Insights (LLM-generated)
    # ------------------------------------------------------------------ #

    async def _build_insights(
        self,
        patient_id: str,
        period_name: str,
        start_date: datetime,
        end_date: datetime,
        snapshot: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Optionally call GPT-4o-mini to synthesize human-friendly insights.
        Returns None if LLM is not configured.
        """
        # Require key to be present
        if not config("OPENAI_API_KEY", default=None):
            return None

        try:
            parser = PydanticOutputParser(pydantic_object=InsightsResponse)
            fmt = parser.get_format_instructions()

            # Build available sections list from data_presence
            data_presence = snapshot.get("data_presence", {})
            available_sections = []
            if data_presence.get("cgm"):
                available_sections.append("glucose")
            if data_presence.get("meals"):
                available_sections.append("meals")
            if data_presence.get("fitness"):
                available_sections.append("activity")
            if data_presence.get("sleep"):
                available_sections.append("sleep")
            if data_presence.get("vitals"):
                available_sections.append("vitals")

            system_msg = SystemMessage(
                content=(
                    "You are a hyper-specialized **Clinical Data Narrative Generation Assistant**.\n\n"
                    "Your SOLE function is to generate qualitative, observational narratives from structured patient data.\n\n"
                    "========================\n"
                    "🚨 CORE & NON-NEGOTIABLE RULES 🚨\n"
                    "========================\n\n"
                    "**1. NO NUMBERS OR QUANTITIES (STRICT BAN):**\n"
                    "   - You MUST NOT express any numerical, quantitative, or measurable concepts. This includes explicit numbers (0, 1, 120), units (mg/dL, steps), counts, ranges, percentages, time duration, frequency, thresholds, or comparative terms implying quantity (e.g., 'only one', 'several', 'most', 'low count', 'minimal', 'maximal', 'extended', 'short duration').\n"
                    "   - Use only neutral, descriptive, observational language (e.g., 'was recorded', 'patterns were present', 'consistent activity').\n\n"
                    "**2. NO ADVICE OR PRESCRIPTION (SAFETY FIRST):**\n"
                    "   - DO NOT provide any medical advice, guidance, recommendations, or prescriptive language (e.g., 'should', 'aim to', 'improve', 'reduce', 'consider').\n"
                    "   - DO NOT infer or suggest risk, deficiency, adequacy, or behavioral changes.\n\n"
                    "**3. JSON OUTPUT ONLY:**\n"
                    "   - Return VALID JSON ONLY. Do NOT include any prose, commentary, markdown (```json), or explanation outside the JSON object.\n\n"
                    "**4. DATA SCOPE:**\n"
                    "   - ONLY reference sections explicitly marked as present in `data_presence`.\n"
                    "   - NEVER mention, imply, or allude to missing data sections, gaps, or availability.\n\n"
                    "**5. INTERNAL FLAGS/ALERTS BAN:**\n"
                    "   - Flags (e.g., 'Low steps (<3000)') are INTERNAL signals. You MUST NOT restate, paraphrase, summarize, or semantically encode them. Stick to raw observations.\n\n"
                    "========================\n"
                    "DETAILED NARRATIVE GUIDELINES\n"
                    "========================\n\n"
                    "**A. Glucose & Vitals:**\n"
                    "   - Describe trends (e.g., stable, variable, consistent, moderate variability). DO NOT use ranges, T.I.R., or mention 'hyper'/'hypo' events.\n\n"
                    "**B. Meals & Nutrition:**\n"
                    "   - ONLY describe meal attributes provided as explicit tags or labels (e.g., 'fiber-rich', 'low GI', 'snack').\n"
                    "   - DO NOT infer nutritional qualities (e.g., 'low carbohydrate', 'insufficient intake') from raw numbers.\n\n"
                    "**C. Tone & Style:**\n"
                    "   - Maintain a Clinical, neutral, non-judgmental, and observational tone.\n"
                    "   - Patient-Presentation fields must be friendly, reassuring, and non-evaluative.\n"
                    "   - Care-Provider fields must be clinical and qualitative, using professional descriptors (e.g., 'subdued post-prandial response').\n\n"
                    "If any instruction conflicts, FOLLOW THIS SYSTEM MESSAGE.\n"
                    "If meaningful insights are limited, populate fields with neutral statements."
                )
            )

            user_msg = HumanMessage(
                content=(
                    "Analyze the provided patient snapshot for a daily summary and generate narrative insights.\n\n"
                    "You must STRICTLY adhere to the SYSTEM MESSAGE and the following output format.\n"
                    "Failure to comply with any rule invalidates the response.\n\n"
                    "========================\n"
                    "AVAILABLE DATA SECTIONS\n"
                    "========================\n\n"
                    f"The following data sections are available for qualitative analysis:\n"
                    f"{', '.join(available_sections) if available_sections else 'none'}\n\n"
                    "Analyze ONLY these sections. Ignore and omit all missing sections.\n\n"
                    "========================\n"
                    "OUTPUT FORMAT & CONSTRAINTS\n"
                    "========================\n\n"
                    "Your output MUST be VALID JSON that conforms EXACTLY to this schema:\n"
                    f"{fmt}\n\n"
                    "STRICTLY qualitative and observational language is required. Remember the ban on ALL numbers, quantities, counts, and prescriptive language.\n\n"
                    "========================\n"
                    "CONTENT MINIMUMS & QUALITY FOCUS\n"
                    "========================\n\n"
                    "- **headline:** One neutral observational sentence summarizing the overall qualitative theme (stability, variability, consistency).\n"
                    "- **key_points:** 2–4 concise observations, aiming to cover *each* available data section.\n"
                    "- **patterns:** 1–3 descriptive correlations between data sections (e.g., activity-glucose association, meal timing patterns).\n"
                    "- **patient_presentation:** **MUST populate BOTH** `short_summary` (1-2 sentences) and `email_summary` (polite, reassuring paragraph).\n"
                    "- **care_provider_presentation:** **MUST populate BOTH** `email_summary` (concise clinical note) and `detailed_summary` (structured qualitative narrative).\n\n"
                    "If meaningful insights are limited, use neutral statements such as:\n"
                    "- 'Tracked data showed stable patterns.'\n"
                    "- 'Recorded metrics remained consistent during the observed period.'\n\n"
                    "========================\n"
                    "CONTEXT\n"
                    "========================\n\n"
                    f"patient_id={patient_id}\n"
                    f"period={period_name}\n"
                    f"window={start_date.isoformat()} to {end_date.isoformat()}\n\n"
                    "========================\n"
                    "PATIENT SNAPSHOT JSON\n"
                    "========================\n\n"
                    f"{snapshot}"
                )
            )

            ai_msg: AIMessage = await self._llm.ainvoke([system_msg, user_msg])
            content = ai_msg.content or "{}"
            parsed = (
                parser.parse(content) if isinstance(content, str) else None
            )
            if parsed:
                # Post-process: ensure key_points and patterns are populated if data exists
                data_presence = snapshot.get("data_presence", {})
                has_data = any(data_presence.values())

                result = parsed.model_dump(exclude_none=True)

                # If we have data but LLM returned empty arrays, add fallback insights
                if has_data:
                    if not result.get("key_points"):
                        result["key_points"] = [
                            "Data collection was consistent for available metrics"
                        ]
                    if not result.get("patterns"):
                        result["patterns"] = [
                            "All tracked metrics were within expected ranges"
                        ]

                # Attempt to log token usage if available on response
                usage = getattr(ai_msg, "response_metadata", None) or {}
                token_usage = usage.get("token_usage") or {}
                await self._log_token_usage_if_available(
                    patient_id=patient_id,
                    model_used=self.MODEL_VERSION,
                    input_tokens=token_usage.get("prompt_tokens"),
                    output_tokens=token_usage.get("completion_tokens"),
                )
                return result
        except Exception:
            # Swallow LLM errors; keep summary generation resilient
            return None
        return None

    async def _log_token_usage_if_available(
        self,
        patient_id: str,
        model_used: str,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
    ) -> None:
        """
        Best-effort token usage logging; ignores failures.
        """
        if input_tokens is None and output_tokens is None:
            return

        try:
            await self.token_usage_service.log_usage(
                user_id=patient_id,
                user_type=ProfileTypeEnum.PATIENT,
                model_used=model_used,
                model_provider="openai",
                input_tokens=input_tokens or 0,
                output_tokens=output_tokens or 0,
                cached_input_tokens=None,
                api_endpoint="patient_summary_insights",
            )
        except Exception:
            # Do not fail the flow if logging fails
            return

    def _period_name_to_dates(
        self, period_name: str, reference_dt: Optional[datetime] = None
    ) -> Tuple[datetime, datetime]:
        now = reference_dt or datetime.now()
        today = now.date()
        yesterday = today - timedelta(days=1)

        period_name_upper = period_name.upper()

        if period_name_upper == "YESTERDAY":
            start_date, end_date = yesterday, yesterday

        elif period_name_upper == "THIS_WEEK":
            week_start = yesterday - timedelta(days=yesterday.weekday())
            start_date, end_date = week_start, yesterday

        elif period_name_upper == "LAST_WEEK":
            week_start = yesterday - timedelta(days=yesterday.weekday())
            last_week_end = week_start - timedelta(days=1)
            last_week_start = last_week_end - timedelta(
                days=last_week_end.weekday()
            )
            start_date, end_date = last_week_start, last_week_end

        elif period_name_upper == "THIS_MONTH":
            month_start = yesterday.replace(day=1)
            start_date, end_date = month_start, yesterday

        elif period_name_upper == "LAST_MONTH":
            this_month_start = yesterday.replace(day=1)
            last_month_end = this_month_start - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            start_date, end_date = last_month_start, last_month_end

        elif period_name_upper == "LAST_30_DAYS":
            start_date = yesterday - timedelta(days=29)  # 30 days inclusive
            end_date = yesterday

        elif period_name_upper == "LAST_90_DAYS":
            start_date = yesterday - timedelta(days=89)  # 90 days inclusive
            end_date = yesterday

        else:
            raise ValueError(f"Unsupported period name: {period_name}")

        start_dt = datetime.combine(
            start_date, datetime.min.time(), tzinfo=None
        )
        end_dt = datetime.combine(end_date, datetime.max.time(), tzinfo=None)
        return start_dt, end_dt

    async def fetch_summary_by_period(
        self, patient_id: str, period_name: str
    ) -> Optional[Dict[str, Any]]:
        start_date, end_date = self._period_name_to_dates(period_name)
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        report_id = self._generate_report_id(
            patient_id, "daily", start_iso, end_iso
        )

        summary = await self.patient_summary_collection.find_one(
            {"_id": report_id}
        )

        return summary

    async def fetch_summary_by_date(
        self, patient_id: str, target_date: date
    ) -> Optional[Dict[str, Any]]:
        start_date = datetime.combine(
            target_date, datetime.min.time(), tzinfo=None
        )
        end_date = datetime.combine(
            target_date, datetime.max.time(), tzinfo=None
        )
        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()
        report_id = self._generate_report_id(
            patient_id, "daily", start_iso, end_iso
        )

        summary = await self.patient_summary_collection.find_one(
            {"_id": report_id}
        )

        return summary

    async def mark_summaries_as_stale(
        self,
        patient_id: str,
        target_date: Optional[date] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        stale_reason: StaleReason = StaleReason.DATA_UPDATED,
    ) -> None:

        if target_date is None and (start_date is None or end_date is None):
            raise ValueError(
                "Either target_date OR both start_date and end_date must be provided"
            )

        now = datetime.now()

        if target_date is not None:
            start_date = datetime.combine(target_date, datetime.min.time())
            end_date = datetime.combine(target_date, datetime.max.time())

        start_iso = start_date.isoformat()
        end_iso = end_date.isoformat()

        query = {
            "patient_id": patient_id,
            "metadata.date_range.start": {"$lte": end_iso},
            "metadata.date_range.end": {"$gte": start_iso},
            "metadata.state": SummaryState.FINALIZED.value,
        }

        await self.patient_summary_collection.update_many(
            query,
            {
                "$set": {
                    "metadata.state": SummaryState.STALE.value,
                    "metadata.data_last_updated_at": now,
                    "metadata.stale_reason": stale_reason.value,
                    "updated_at": now,
                },
                "$unset": {
                    "metadata.regenerated_at": "",
                    "metadata.regenerated_by": "",
                },
            },
        )

    async def get_stale_summaries(self) -> List[Dict[str, Any]]:
        query = {
            "metadata.state": SummaryState.STALE.value,
        }
        
        cursor = self.patient_summary_collection.find(query)
        summaries = await cursor.to_list(length=None)
        
        return summaries
