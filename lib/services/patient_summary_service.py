from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from decouple import config
from langchain.output_parsers import PydanticOutputParser
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import func, select

from lib.core.constants import SYSTEM_USER_ID, ProfileTypeEnum
from lib.services.token_usage_service import TokenUsageService


class InsightsPayload(BaseModel):
    headline: Optional[str] = Field(
        default=None, description="One short headline insight"
    )
    key_points: List[str] = Field(
        default_factory=list, description="Up to 4 bullet key points"
    )
    patterns: List[str] = Field(
        default_factory=list, description="Up to 4 observed patterns/correlations"
    )
    attention_flags: List[str] = Field(
        default_factory=list,
        description="Up to 4 risk/safety flags requiring attention",
    )


class Presentation(BaseModel):
    short_summary: Optional[str] = Field(
        default=None, description="1-2 sentence plain summary"
    )
    email_summary: Optional[str] = Field(
        default=None, description="Patient-friendly email-style summary"
    )
    detailed_summary: Optional[str] = Field(
        default=None,
        description="Detailed clinical summary for care providers with specific metrics, thresholds, and actionable recommendations",
    )


class InsightsResponse(BaseModel):
    insights: InsightsPayload
    presentation: Presentation


class PatientSummaryService:
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
            model="gpt-4o-mini",  # type: ignore
            temperature=0.4,
            api_key=SecretStr(str(config("OPENAI_API_KEY"))),
        )

    async def summarize_periods(
        self,
        patient_id: str,
        periods: Iterable[Tuple[str, datetime, datetime]],
    ) -> None:
        """
        Upserts rich summary documents for each requested period.

        For now this is optimized for *daily* windows (e.g. yesterday),
        but it will also work for longer ranges by aggregating over the
        full [start_date, end_date] window.
        """

        now = datetime.utcnow()
        for period_name, start_date, end_date in periods:
            summary = await self._build_summary_snapshot(
                patient_id, period_name, start_date, end_date
            )
            await self.patient_summary_collection.update_one(
                {
                    "patient_id": patient_id,
                    "period_name": period_name,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                {
                    "$set": {
                        "patient_id": patient_id,
                        "period_name": period_name,
                        "report_type": "daily_snapshot",
                        "date": end_date.date().isoformat(),
                        "start_date": start_date,
                        "end_date": end_date,
                        "generated_at": now,
                        **summary,
                    }
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
          "date": "YYYY-MM-DD",
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
            "fitness": activity is not None
            and activity.get("steps") not in (None, 0),
            "sleep": sleep is not None
            and sleep.get("duration_hours") not in (None, 0),
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
            if glucose.get("avg_mgdl") is not None and glucose["avg_mgdl"] > 180:
                flags.append("High average glucose (>180 mg/dL)")
            if glucose.get("variability_pct") is not None and glucose[
                "variability_pct"
            ] > 36:
                flags.append("High glucose variability (>36%)")
            if glucose.get("hyper_event_count", 0) > 0:
                flags.append("Hyperglycemia events detected")
            if glucose.get("hypo_event_count", 0) > 0:
                flags.append("Hypoglycemia events detected")
            elif glucose.get("hypo_event_count", 0) == 0:
                flags.append("No hypoglycemia events detected")

        if data_presence["meals"] and meals:
            if meals.get("meal_count", 0) < 2:
                flags.append("Low meal logging (<2 meals)")
            best = meals.get("best_meal") or {}
            if best and best.get("score") is not None and best["score"] < 5:
                flags.append("No well-scored meals")
            totals = meals.get("nutrition_totals") or {}
            if totals and totals.get("protein_g") is not None and totals[
                "protein_g"
            ] < 50:
                flags.append("Low protein intake (<50g)")

        if data_presence["fitness"] and activity:
            if activity.get("steps", 0) < 3000:
                flags.append("Low steps (<3000)")
            if activity.get("active_minutes", 0) < 30:
                flags.append("Low active minutes (<30)")
            if activity.get("longest_inactive_minutes", 0) > 180:
                flags.append("Prolonged inactivity (>3h)")

        if data_presence["sleep"] and sleep:
            if sleep.get("duration_hours") is not None and sleep[
                "duration_hours"
            ] < 6:
                flags.append("Short sleep (<6h)")
            if sleep.get("efficiency_pct") is not None and sleep[
                "efficiency_pct"
            ] < 75:
                flags.append("Low sleep efficiency (<75%)")

        if data_presence["vitals"] and vitals:
            if vitals.get("blood_pressure_avg") is None:
                flags.append("No blood pressure data")
            if vitals.get("weight_kg") is None:
                flags.append("No weight data")

        return {
            "patient_id": patient_id,
            "date": period_date.isoformat(),
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
        doc = await self.cgm_reports_collection.find_one(
            {
                "patient_id": patient_id,
                "report_type": "daily",
                "start_date": {"$gte": start_date, "$lte": end_date},
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
        below = (
            (ranges.get("below_54_percent", 0.0))
            + (ranges.get("below_70_above_54_percent", 0.0))
        )
        above = (
            (ranges.get("above_180_below_250_percent", 0.0))
            + (ranges.get("above_250_percent", 0.0))
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
        doc = await self.meal_reports_collection.find_one(
            {
                "patient_id": patient_id,
                "report_type": "daily",
                "date": report_date.isoformat(),
            }
        )
        if not doc:
            return None

        meals: List[Dict[str, Any]] = doc.get("meals", []) or []

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
                    "meal_id": str(m.get("id"))
                    if m.get("id") is not None
                    else None,
                    "name": m.get("name"),
                    "type": m.get("type"),
                    "score": m.get("score"),
                    "carbs_g": macro.get("carbohydrates"),
                    "tags": m.get("tags", []),
                    "image_url": m.get("image_url"),
                    "description": m.get("description"),
                }

            best_meal = _meal_view(best)
            worst_meal = _meal_view(worst)

        nutrition_totals = {
            "calories": doc.get("calories"),
            "carbs_g": doc.get("carbohydrates"),
            "protein_g": doc.get("proteins"),
            "fat_g": doc.get("fats"),
            "fiber_g": doc.get("fiber"),
        }

        return {
            "meal_count": doc.get("meal_count", 0),
            "best_meal": best_meal,
            "worst_meal": worst_meal,
            "nutrition_totals": nutrition_totals,
        }

    async def _build_activity_section(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> Optional[Dict[str, Any]]:
        doc = await self.fitness_reports_collection.find_one(
            {
                "patient_id": patient_id,
                "report_type": "daily",
                "start_date": {"$gte": start_date, "$lte": end_date},
            }
        )
        if not doc:
            return None

        inactive_periods: List[Dict[str, Any]] = (
            doc.get("inactive_periods", []) or []
        )
        longest_inactive = max(
            (p.get("inactive_duration", 0) for p in inactive_periods), default=0
        )

        peak = doc.get("peak_activity_time") or {}

        return {
            "steps": doc.get("steps", 0),
            "active_minutes": doc.get("active_duration", 0),
            "longest_inactive_minutes": longest_inactive,
            "peak_activity_hour": peak.get("hour"),
        }

    async def _build_sleep_section(
        self, patient_id: str, start_date: datetime, end_date: datetime
    ) -> Optional[Dict[str, Any]]:
        doc = await self.sleep_reports_collection.find_one(
            {
                "patient_id": patient_id,
                "report_type": "daily",
                "start_date": {"$gte": start_date, "$lte": end_date},
            }
        )
        if not doc:
            return None

        duration = doc.get("duration_analysis") or {}
        quality = doc.get("quality_analysis") or {}

        total_minutes = duration.get("total_duration") or 0
        duration_hours = round(total_minutes / 60, 1) if total_minutes else 0.0

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
                    "You are a clinical summarizer. "
                    "Return concise JSON only, no prose. "
                    "CRITICAL: Only reference data sections that are present in the snapshot. "
                    "Do NOT mention sections that are missing (check data_presence). "
                    "Include actionable, safety-aware phrasing. "
                    "Generate three types of summaries: short_summary (patient-friendly 1-2 sentences), "
                    "email_summary (patient-friendly email style), and detailed_summary (clinical summary for care providers "
                    "with specific metrics, thresholds, and actionable recommendations)."
                )
            )
            user_msg = HumanMessage(
                content=(
                    f"Generate insights for a daily snapshot. "
                    f"Available data sections: {', '.join(available_sections) if available_sections else 'none'}.\n"
                    f"ONLY analyze and mention these available sections. Ignore any missing sections.\n"
                    f"Respond strictly using this format:\n"
                    f"{fmt}\n"
                    'Keep each list <=4 items, concise, no PHI. Use short, direct phrases. Avoid emojis or markdown.\n'
                    'For detailed_summary: Include specific metrics, clinical thresholds, and actionable recommendations for care providers.\n'
                    f"patient_id={patient_id}, period={period_name}, "
                    f"window={start_date.isoformat()} to {end_date.isoformat()}. "
                    "Snapshot JSON (check data_presence to see which sections are available):\n"
                    f"{snapshot}"
                )
            )

            ai_msg: AIMessage = await self._llm.ainvoke([system_msg, user_msg])
            content = ai_msg.content or "{}"
            parsed = parser.parse(content) if isinstance(content, str) else None
            if parsed:
                # Attempt to log token usage if available on response
                usage = getattr(ai_msg, "response_metadata", None) or {}
                token_usage = usage.get("token_usage") or {}
                await self._log_token_usage_if_available(
                    patient_id=patient_id,
                    model_used="gpt-4o-mini",
                    input_tokens=token_usage.get("prompt_tokens"),
                    output_tokens=token_usage.get("completion_tokens"),
                )
                return parsed.model_dump(exclude_none=True)
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
