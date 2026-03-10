import json
from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from decouple import config
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.core.postgres_store import PostgresStore
from lib.models.agent_meal_feature_cache import AgentMealFeatureCache
from lib.models.agent_meal_snapshot import AgentMealSnapshot
from lib.models.patient_smbg import PatientSMBG
from lib.models.patient_vital import PatientVital
from lib.schemas.agent_meal_v1 import (
    CareProviderView,
    DataUsedFlags,
    GlycemicResponse,
    HistoricalComparison,
    MealAgentMessage,
    MealAgentRequest,
    MealAgentResponseData,
    MealAgentScores,
    MealAgentVerdicts,
    SnapshotReadResponse,
)
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.meal import MealService
from lib.services.qdrant_search_engine.qdrant_search_engine import QdrantSearchEngine
from lib.services.reports import CGMReportService, FitnessReportService, MealReportService
from lib.services.reports import SleepReportService
from lib.services.reports.cgm.processor import CGMStatsProcessor
from lib.services.reports.fitness.processor import FitnessStatsProcessor
from lib.services.reports.meal.processor import MealStatsProcessor
from lib.services.patient_sleep_service import PatientSleepService
from lib.utils.postgres_session_decorator import with_postgres_session
from lib.utils.retry_utils import retry_request


class Pass1PlannerOutput(BaseModel):
    priority_findings: List[str]
    missing_critical_data: List[str]
    comparison_focus: str
    action_focus: str


class Pass2ResponderOutput(BaseModel):
    summary_text: str
    trend_note: str
    next_best_actions: List[str]
    care_provider_evidence_points: Optional[List[Dict[str, Any]]] = None
    care_provider_metrics_table: Optional[Dict[str, Any]] = None


class AgentMealV1Service:
    HISTORY_WINDOW_DAYS = 14
    FEATURE_CACHE_TTL_MIN = 30

    def __init__(
        self,
        postgres_store: PostgresStore,
        meal_service: MealService,
        meal_report_service: MealReportService,
        cgm_report_service: CGMReportService,
        fitness_report_service: FitnessReportService,
        sleep_report_service: SleepReportService,
        meal_stats_processor: MealStatsProcessor,
        cgm_stats_processor: CGMStatsProcessor,
        fitness_stats_processor: FitnessStatsProcessor,
        patient_sleep_service: PatientSleepService,
        qdrant_search_engine: QdrantSearchEngine,
        agent_meal_messages_collection: Any,
    ):
        self.postgres_store = postgres_store
        self.meal_service = meal_service
        self.meal_report_service = meal_report_service
        self.cgm_report_service = cgm_report_service
        self.fitness_report_service = fitness_report_service
        self.sleep_report_service = sleep_report_service
        self.meal_stats_processor = meal_stats_processor
        self.cgm_stats_processor = cgm_stats_processor
        self.fitness_stats_processor = fitness_stats_processor
        self.patient_sleep_service = patient_sleep_service
        self.qdrant_search_engine = qdrant_search_engine
        self.agent_meal_messages_collection = agent_meal_messages_collection
        self._indexes_initialized = False

        self.chat_model = None
        self.pass1_model = None
        self.pass2_model = None
        self._init_llm_models()

    def _init_llm_models(self) -> None:
        try:
            api_key = str(config("OPENAI_API_KEY"))
            self.chat_model = ChatOpenAI(
                model="gpt-4.1-mini",
                temperature=0.2,
                api_key=SecretStr(api_key),
            )
            self.pass1_model = self.chat_model.with_structured_output(
                Pass1PlannerOutput,
                include_raw=False,
            )
            self.pass2_model = self.chat_model.with_structured_output(
                Pass2ResponderOutput,
                include_raw=False,
            )
        except Exception:
            self.chat_model = None
            self.pass1_model = None
            self.pass2_model = None

    @with_postgres_session
    async def respond(
        self,
        payload: MealAgentRequest,
        *,
        postgres_session: AsyncSession,
    ) -> MealAgentResponseData:
        conversation_id = payload.conversation_id or self._build_conversation_id(
            payload.patient_id,
            payload.meal_id,
        )
        resolved_mode = self._resolve_mode(payload.mode, payload.meal_id)

        if not self._indexes_initialized:
            await self.ensure_indexes()
            self._indexes_initialized = True

        await self._insert_message(
            conversation_id=conversation_id,
            patient_id=str(payload.patient_id),
            meal_id=str(payload.meal_id) if payload.meal_id else None,
            audience=payload.audience,
            role="user",
            content=payload.message,
            message_type="text",
        )

        features, source_flags, evidence, warnings = await self._get_or_build_features(
            patient_id=payload.patient_id,
            meal_id=payload.meal_id,
            mode=resolved_mode,
            postgres_session=postgres_session,
        )

        history_messages = await self._fetch_recent_messages(conversation_id)
        pass1_result = await self._run_pass1(
            message=payload.message,
            features=features,
            warnings=warnings,
        )
        pass2_result = await self._run_pass2(
            message=payload.message,
            audience=payload.audience,
            mode=resolved_mode,
            meal_id=payload.meal_id,
            pass1_result=pass1_result,
            features=features,
            history_messages=history_messages,
        )

        response = self._build_response(
            conversation_id=conversation_id,
            audience=payload.audience,
            features=features,
            source_flags=source_flags,
            warnings=warnings,
            pass2_result=pass2_result,
            debug_enabled=payload.debug,
            evidence=evidence,
            mode=resolved_mode,
            meal_id=payload.meal_id,
        )

        snapshot_id = await self._persist_snapshot(
            payload=payload,
            conversation_id=conversation_id,
            mode=resolved_mode,
            features=features,
            evidence=evidence,
            output=response.model_dump(mode="json"),
            pass1_json=pass1_result.model_dump(mode="json"),
            model_meta=self._build_model_meta(),
            postgres_session=postgres_session,
        )
        response.snapshot_id = snapshot_id

        await self._insert_message(
            conversation_id=conversation_id,
            patient_id=str(payload.patient_id),
            meal_id=str(payload.meal_id) if payload.meal_id else None,
            audience=payload.audience,
            role="assistant",
            content=response.summary_text,
            message_type="json_ref",
            snapshot_id=str(snapshot_id),
        )

        return response

    @with_postgres_session
    async def fetch_snapshot(
        self,
        snapshot_id: UUID,
        *,
        postgres_session: AsyncSession,
    ) -> Optional[SnapshotReadResponse]:
        result = await postgres_session.execute(
            select(AgentMealSnapshot).where(
                AgentMealSnapshot.snapshot_id == snapshot_id
            )
        )
        row = result.scalars().first()
        if not row:
            return None

        return SnapshotReadResponse(
            snapshot_id=row.snapshot_id,
            patient_id=row.patient_id,
            meal_id=row.meal_id,
            conversation_id=row.conversation_id,
            audience=row.audience,
            mode=row.mode,
            data_source_strategy=row.data_source_strategy,
            features_json=row.features_json or {},
            evidence_json=row.evidence_json or {},
            output_json=row.output_json or {},
            pass1_json=row.pass1_json or {},
            model_meta_json=row.model_meta_json or {},
            created_at=row.created_at,
        )

    async def fetch_conversation_messages(
        self,
        conversation_id: str,
    ) -> List[MealAgentMessage]:
        cursor = self.agent_meal_messages_collection.find(
            {"conversation_id": conversation_id},
        ).sort("created_at", 1)
        rows = await cursor.to_list(length=500)

        parsed: List[MealAgentMessage] = []
        for row in rows:
            parsed.append(
                MealAgentMessage(
                    id=str(row["_id"]),
                    conversation_id=row["conversation_id"],
                    patient_id=row["patient_id"],
                    meal_id=row.get("meal_id"),
                    audience=row["audience"],
                    role=row["role"],
                    content=row["content"],
                    message_type=row.get("message_type", "text"),
                    snapshot_id=row.get("snapshot_id"),
                    created_at=row.get("created_at", datetime.utcnow()),
                )
            )
        return parsed

    async def ensure_indexes(self) -> None:
        await self.agent_meal_messages_collection.create_index(
            [("conversation_id", 1), ("created_at", 1)],
            name="agent_meal_conv_created_idx",
        )
        await self.agent_meal_messages_collection.create_index(
            [("patient_id", 1), ("created_at", -1)],
            name="agent_meal_patient_created_desc_idx",
        )

    async def _get_or_build_features(
        self,
        patient_id: UUID,
        meal_id: Optional[UUID],
        mode: str,
        postgres_session: AsyncSession,
    ) -> tuple[Dict[str, Any], Dict[str, bool], Dict[str, Any], List[str]]:
        now = datetime.now().replace(tzinfo=None)
        window_end = datetime.combine(now.date(), time.max).replace(microsecond=0)
        window_start = datetime.combine(
            now.date() - timedelta(days=self.HISTORY_WINDOW_DAYS),
            time.min,
        )

        cached = await postgres_session.execute(
            select(AgentMealFeatureCache).where(
                and_(
                    AgentMealFeatureCache.patient_id == patient_id,
                    AgentMealFeatureCache.meal_id == meal_id,
                    AgentMealFeatureCache.window_start == window_start,
                    AgentMealFeatureCache.window_end == window_end,
                    AgentMealFeatureCache.expires_at > now,
                )
            )
        )
        cache_row = cached.scalars().first()
        if cache_row:
            return (
                cache_row.feature_bundle_json or {},
                cache_row.source_flags_json or {},
                {"cache_hit": True},
                [],
            )

        feature_bundle, source_flags, evidence, warnings = await self._build_features(
            patient_id=patient_id,
            meal_id=meal_id,
            mode=mode,
            window_start=window_start,
            window_end=window_end,
            postgres_session=postgres_session,
        )

        expires_at = now + timedelta(minutes=self.FEATURE_CACHE_TTL_MIN)
        cache_model = AgentMealFeatureCache(
            patient_id=patient_id,
            meal_id=meal_id,
            window_start=window_start,
            window_end=window_end,
            feature_bundle_json=feature_bundle,
            source_flags_json=source_flags,
            expires_at=expires_at,
        )
        postgres_session.add(cache_model)
        await postgres_session.commit()

        return feature_bundle, source_flags, evidence, warnings

    async def _build_features(
        self,
        patient_id: UUID,
        meal_id: Optional[UUID],
        mode: str,
        window_start: datetime,
        window_end: datetime,
        postgres_session: AsyncSession,
    ) -> tuple[Dict[str, Any], Dict[str, bool], Dict[str, Any], List[str]]:
        source_flags = {
            "reports": False,
            "raw_fallback_used": False,
            "cgm": False,
            "smbg": False,
            "sleep": False,
            "fitness": False,
            "vitals": False,
            "qdrant": False,
        }
        warnings: List[str] = []
        evidence: Dict[str, Any] = {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }

        meal_obj = None
        meal_date = window_end.date()
        history_end_date = meal_date
        current_meal_source = "time_bucket_inference"
        current_meal = {
            "meal_type": "unknown",
            "time_bucket": self._time_bucket(datetime.now().time()),
            "calories": 0.0,
            "carbs": 0.0,
            "protein": 0.0,
            "fat": 0.0,
            "fiber": 0.0,
        }

        if meal_id:
            meal_obj = await self.meal_service.fetch_meal(
                str(meal_id),
                postgres_session=postgres_session,
            )
            meal_schema = PatientMealSchema.from_orm(meal_obj)
            meal_date = meal_schema.date
            meal_time = meal_schema.time
            total_macro = meal_schema.total_macro_nutritional_value
            current_meal = {
                "meal_type": meal_schema.type or "unknown",
                "time_bucket": self._time_bucket(meal_time),
                "calories": float(total_macro.calories if total_macro else 0),
                "carbs": float(total_macro.carbohydrates if total_macro else 0),
                "protein": float(total_macro.proteins if total_macro else 0),
                "fat": float(total_macro.fats if total_macro else 0),
                "fiber": float(total_macro.fiber if total_macro else 0),
            }
            current_meal_source = "uploaded_meal"
        else:
            inferred_type = self._infer_meal_type_from_bucket(
                current_meal["time_bucket"]
            )
            current_meal["meal_type"] = inferred_type

        diet_recommendation = await self.meal_stats_processor.get_diet_recommendation(
            str(patient_id), meal_date
        )
        target = self._pick_meal_target(
            meal_type=current_meal["meal_type"],
            diet_recommendation=diet_recommendation.model_dump(mode="json"),
        )

        meal_reports = await self.meal_report_service.fetch_daily_reports_in_range(
            str(patient_id),
            history_end_date - timedelta(days=self.HISTORY_WINDOW_DAYS),
            history_end_date,
        )
        source_flags["reports"] = bool(meal_reports)
        evidence["meal_reports_count"] = len(meal_reports)
        if not meal_reports:
            warnings.append("Meal reports unavailable; historical comparisons limited.")
        elif not meal_obj:
            latest_meal, latest_meal_date = self._select_latest_meal_from_reports(
                meal_reports
            )
            evidence["latest_meal_found"] = latest_meal is not None
            if latest_meal:
                macros = latest_meal.get("total_macro_nutritional_value", {}) or {}
                meal_type = (latest_meal.get("type") or "snack").lower()
                meal_time = self._parse_time_safe(str(latest_meal.get("time", "")))
                if latest_meal_date:
                    meal_date = latest_meal_date
                    history_end_date = latest_meal_date
                current_meal = {
                    "meal_type": meal_type,
                    "time_bucket": self._time_bucket(
                        meal_time or datetime.now().time()
                    ),
                    "calories": float(macros.get("calories") or 0),
                    "carbs": float(macros.get("carbohydrates") or 0),
                    "protein": float(macros.get("proteins") or 0),
                    "fat": float(macros.get("fats") or 0),
                    "fiber": float(macros.get("fiber") or 0),
                }
                current_meal_source = "latest_reported_meal"
                target = self._pick_meal_target(
                    meal_type=current_meal["meal_type"],
                    diet_recommendation=diet_recommendation.model_dump(mode="json"),
                )
            meal_reports = await self.meal_report_service.fetch_daily_reports_in_range(
                str(patient_id),
                history_end_date - timedelta(days=self.HISTORY_WINDOW_DAYS),
                history_end_date,
            )
            source_flags["reports"] = bool(meal_reports)
            evidence["meal_reports_count"] = len(meal_reports)

        historical = self._build_historical_comparison(current_meal, meal_reports)
        evidence["historical_cohort_size"] = historical["cohort_size"]
        evidence["anchor_date"] = history_end_date.isoformat()
        evidence["historical_cohort_selection"] = historical.get(
            "cohort_selection", "none"
        )
        evidence["current_meal_source"] = current_meal_source

        if all(float(target.get(key, 0) or 0) <= 0 for key in ("calories", "carbs", "protein", "fat", "fiber")):
            warnings.append(
                "Diet plan targets are not configured; verdicts are based on default neutral thresholds."
            )

        cgm_response = await self._build_cgm_response(
            patient_id=str(patient_id),
            meal_obj=meal_obj,
            meal_date=meal_date,
            source_flags=source_flags,
            warnings=warnings,
        )

        smbg_context = await self._fetch_smbg_context(
            patient_id=patient_id,
            meal_obj=meal_obj,
            postgres_session=postgres_session,
            source_flags=source_flags,
        )
        vitals_context = await self._fetch_vitals_context(
            patient_id=patient_id,
            meal_date=meal_date,
            postgres_session=postgres_session,
            source_flags=source_flags,
        )
        sleep_context = await self._fetch_sleep_context(
            patient_id=str(patient_id),
            meal_date=meal_date,
            source_flags=source_flags,
            warnings=warnings,
        )
        fitness_context = await self._fetch_fitness_context(
            patient_id=str(patient_id),
            meal_date=meal_date,
            source_flags=source_flags,
            warnings=warnings,
        )
        qdrant_context = await self._fetch_qdrant_context(
            patient_id=str(patient_id),
            meal_obj=meal_obj,
            source_flags=source_flags,
        )

        verdicts = self._build_verdicts(current_meal=current_meal, target=target)

        feature_bundle = {
            "mode": mode,
            "current_meal": current_meal,
            "current_meal_source": current_meal_source,
            "target": target,
            "verdicts": verdicts,
            "historical_comparison": historical,
            "glycemic_response": cgm_response,
            "smbg_context": smbg_context,
            "sleep_context": sleep_context,
            "fitness_context": fitness_context,
            "vitals_context": vitals_context,
            "qdrant_context": qdrant_context,
        }
        evidence["source_flags"] = source_flags

        return feature_bundle, source_flags, evidence, warnings

    async def _build_cgm_response(
        self,
        patient_id: str,
        meal_obj: Any,
        meal_date: date,
        source_flags: Dict[str, bool],
        warnings: List[str],
    ) -> Dict[str, Any]:
        cgm_report = await self.cgm_report_service.fetch_daily_report(
            patient_id,
            meal_date,
        )
        if cgm_report:
            source_flags["reports"] = True

        before_values: List[tuple[datetime, float]] = []
        after_values: List[tuple[datetime, float]] = []

        if cgm_report and meal_obj:
            meal_report = cgm_report.get("meal_report") or {}
            for meal in meal_report.get("meals", []) if isinstance(meal_report, dict) else []:
                if str(meal.get("id")) != str(meal_obj.id):
                    continue
                before_values = self._normalize_glucose_series(
                    meal.get("glucose_before_meal") or []
                )
                after_values = self._normalize_glucose_series(
                    meal.get("glucose_after_meal") or []
                )
                break

        if meal_obj and (not before_values and not after_values):
            source_flags["raw_fallback_used"] = True
            before_raw, after_raw = self.cgm_stats_processor.get_readings_around_meal(
                patient_id,
                datetime.combine(meal_obj.date, meal_obj.time),
            )
            before_values = self._normalize_glucose_series(before_raw)
            after_values = self._normalize_glucose_series(after_raw)
            if before_values or after_values:
                source_flags["cgm"] = True

        if not before_values and not after_values:
            if meal_obj:
                warnings.append("No CGM readings found for meal window.")
            return {}

        source_flags["cgm"] = True

        baseline = (
            sum(v for _, v in before_values) / len(before_values)
            if before_values
            else None
        )
        peak_pair = max(after_values, key=lambda item: item[1]) if after_values else None
        peak = peak_pair[1] if peak_pair else None

        delta = (peak - baseline) if (peak is not None and baseline is not None) else None
        time_to_peak = None
        if peak_pair and meal_obj:
            meal_dt = datetime.combine(meal_obj.date, meal_obj.time)
            time_to_peak = int((peak_pair[0] - meal_dt).total_seconds() / 60)

        return_to_baseline = None
        if baseline is not None and after_values:
            for ts, value in after_values:
                if meal_obj and ts >= datetime.combine(meal_obj.date, meal_obj.time) + timedelta(hours=2):
                    return_to_baseline = value <= baseline + 10
                    break

        return {
            "baseline_mgdl": round(baseline, 2) if baseline is not None else None,
            "peak_mgdl": round(peak, 2) if peak is not None else None,
            "delta_mgdl": round(delta, 2) if delta is not None else None,
            "time_to_peak_min": time_to_peak,
            "return_to_baseline_2h": return_to_baseline,
        }

    async def _fetch_smbg_context(
        self,
        patient_id: UUID,
        meal_obj: Any,
        postgres_session: AsyncSession,
        source_flags: Dict[str, bool],
    ) -> Dict[str, Any]:
        if not meal_obj:
            return {}

        meal_dt = datetime.combine(meal_obj.date, meal_obj.time)
        start_dt = meal_dt - timedelta(minutes=90)
        end_dt = meal_dt + timedelta(minutes=180)
        query = (
            select(PatientSMBG)
            .where(
                and_(
                    PatientSMBG.patient_id == patient_id,
                    PatientSMBG.reading_time >= start_dt,
                    PatientSMBG.reading_time <= end_dt,
                )
            )
            .order_by(PatientSMBG.reading_time.asc())
        )
        result = await postgres_session.execute(query)
        rows = result.scalars().all()
        if rows:
            source_flags["smbg"] = True
        return {
            "count": len(rows),
            "readings": [
                {
                    "time": row.reading_time.isoformat(),
                    "glucose_level": row.glucose_level,
                    "type": row.type,
                }
                for row in rows[-5:]
            ],
        }

    async def _fetch_vitals_context(
        self,
        patient_id: UUID,
        meal_date: date,
        postgres_session: AsyncSession,
        source_flags: Dict[str, bool],
    ) -> Dict[str, Any]:
        start_dt = datetime.combine(meal_date - timedelta(days=7), time.min)
        end_dt = datetime.combine(meal_date, time.max)

        query = (
            select(PatientVital)
            .where(
                and_(
                    PatientVital.patient_id == patient_id,
                    PatientVital.test_time >= start_dt,
                    PatientVital.test_time <= end_dt,
                )
            )
            .order_by(PatientVital.test_time.desc())
            .limit(1)
        )
        result = await postgres_session.execute(query)
        vital = result.scalars().first()
        if not vital:
            return {}
        source_flags["vitals"] = True
        return {
            "test_time": vital.test_time.isoformat(),
            "weight": vital.weight,
            "systolic_bp": vital.systolic_bp,
            "diastolic_bp": vital.diastolic_bp,
            "heart_rate": vital.heart_rate,
        }

    async def _fetch_sleep_context(
        self,
        patient_id: str,
        meal_date: date,
        source_flags: Dict[str, bool],
        warnings: List[str],
    ) -> Dict[str, Any]:
        prior_date = meal_date - timedelta(days=1)
        report = await self.sleep_report_service.fetch_daily_report(
            patient_id,
            prior_date,
        )
        if report:
            source_flags["reports"] = True
            source_flags["sleep"] = True
            return {
                "report_available": True,
                "summary": report.get("summary", {}),
            }

        source_flags["raw_fallback_used"] = True
        raw = await self.patient_sleep_service.get_daily_sleep_data(
            patient_id,
            prior_date,
        )
        if raw:
            source_flags["sleep"] = True
            return {"report_available": False, "raw": raw}

        warnings.append("Sleep data unavailable for prior night.")
        return {}

    async def _fetch_fitness_context(
        self,
        patient_id: str,
        meal_date: date,
        source_flags: Dict[str, bool],
        warnings: List[str],
    ) -> Dict[str, Any]:
        report = await self.fitness_report_service.fetch_daily_report(
            patient_id,
            meal_date,
        )
        if report:
            source_flags["reports"] = True
            source_flags["fitness"] = True
            return {
                "report_available": True,
                "steps": report.get("steps"),
                "active_duration": report.get("active_duration"),
                "active_energy": report.get("active_energy"),
            }

        start_dt = datetime.combine(meal_date, time.min)
        end_dt = datetime.combine(meal_date, time.max)
        raw = self.fitness_stats_processor.generate_custom_report(
            patient_id=patient_id,
            start_date=start_dt,
            end_date=end_dt,
            report_type="daily",
        )
        source_flags["raw_fallback_used"] = True
        if raw:
            source_flags["fitness"] = True
            return {
                "report_available": False,
                "steps": raw.steps,
                "active_duration": raw.active_duration,
                "active_energy": raw.active_energy,
            }
        warnings.append("Fitness data unavailable for meal date.")
        return {}

    async def _fetch_qdrant_context(
        self,
        patient_id: str,
        meal_obj: Any,
        source_flags: Dict[str, bool],
    ) -> Dict[str, Any]:
        if not meal_obj:
            return {"neighbors": []}

        query_text = " ".join(
            [
                str(meal_obj.name or ""),
                str(meal_obj.type or ""),
                str(meal_obj.description or ""),
            ]
        ).strip()
        if not query_text:
            return {"neighbors": []}

        try:
            search_results = await self.qdrant_search_engine.search(
                query=query_text,
                limit=5,
                patient_ids=[patient_id],
                data_types=["meal"],
            )
            source_flags["qdrant"] = bool(search_results.get("results"))
            neighbors = []
            for point in search_results.get("results", [])[:5]:
                payload = getattr(point, "payload", {}) or {}
                neighbors.append(
                    {
                        "meal_id": payload.get("meal_id"),
                        "meal_type": payload.get("meal_type"),
                        "score": round(getattr(point, "score", 0.0), 4),
                    }
                )
            return {"neighbors": neighbors}
        except Exception:
            return {"neighbors": []}

    async def _run_pass1(
        self,
        message: str,
        features: Dict[str, Any],
        warnings: List[str],
    ) -> Pass1PlannerOutput:
        if not self.pass1_model:
            return Pass1PlannerOutput(
                priority_findings=[
                    "Evaluate plan adherence and trend against recent history."
                ],
                missing_critical_data=warnings,
                comparison_focus="same_meal_type_time_bucket",
                action_focus="nutrition_and_glycemic_stability",
            )

        system_prompt = (
            "You are an analysis planner. Return strict JSON only. "
            "No chain of thought. Focus on findings, missing data, "
            "comparison focus and action focus."
        )
        user_payload = {
            "message": message,
            "features": features,
            "warnings": warnings,
        }
        try:
            output = retry_request(
                self.pass1_model.invoke,
                input=[
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=json.dumps(user_payload)),
                ],
            )
            return output
        except Exception:
            return Pass1PlannerOutput(
                priority_findings=[
                    "Evaluate plan adherence and trend against recent history."
                ],
                missing_critical_data=warnings,
                comparison_focus="same_meal_type_time_bucket",
                action_focus="nutrition_and_glycemic_stability",
            )

    async def _run_pass2(
        self,
        message: str,
        audience: str,
        mode: str,
        meal_id: Optional[UUID],
        pass1_result: Pass1PlannerOutput,
        features: Dict[str, Any],
        history_messages: List[MealAgentMessage],
    ) -> Pass2ResponderOutput:
        if not self.pass2_model:
            trend_note = features.get("historical_comparison", {}).get("trend_note", "")
            summary = (
                "Meal guidance generated from current data and the last 14 days."
            )
            actions = self._fallback_actions(features)
            return Pass2ResponderOutput(
                summary_text=summary,
                trend_note=trend_note,
                next_best_actions=actions,
                care_provider_evidence_points=[],
                care_provider_metrics_table={},
            )

        history = [
            {"role": m.role, "content": m.content}
            for m in history_messages[-6:]
        ]
        mode_instruction = ""
        if mode == "pre_meal" and not meal_id:
            mode_instruction = (
                "The user has not eaten this meal yet. Frame output as "
                "forward-looking recommendations based on recent patterns. "
                "Do not call it the current eaten meal."
            )
        system_prompt = (
            "You are a meal agent responder. Return strict JSON only and keep the "
            "response concise. Do not reveal chain of thought. "
            + mode_instruction
        )
        user_payload = {
            "audience": audience,
            "mode": mode,
            "message": message,
            "pass1": pass1_result.model_dump(mode="json"),
            "features": features,
            "history": history,
        }
        try:
            output = retry_request(
                self.pass2_model.invoke,
                input=[
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=json.dumps(user_payload)),
                ],
            )
            return output
        except Exception:
            trend_note = features.get("historical_comparison", {}).get(
                "trend_note", ""
            )
            actions = self._fallback_actions(features)
            return Pass2ResponderOutput(
                summary_text=(
                    "Meal guidance generated from available data and recent history."
                ),
                trend_note=trend_note,
                next_best_actions=actions,
                care_provider_evidence_points=[],
                care_provider_metrics_table={},
            )

    def _build_response(
        self,
        conversation_id: str,
        audience: str,
        features: Dict[str, Any],
        source_flags: Dict[str, bool],
        warnings: List[str],
        pass2_result: Pass2ResponderOutput,
        debug_enabled: bool,
        evidence: Dict[str, Any],
        mode: str,
        meal_id: Optional[UUID],
    ) -> MealAgentResponseData:
        current = features.get("current_meal", {})
        verdicts = features.get("verdicts", {})
        hist = features.get("historical_comparison", {})
        gly = features.get("glycemic_response", {}) or None

        scores = self._compute_scores(features=features, source_flags=source_flags)
        confidence = self._compute_confidence(source_flags, warnings)
        trend_note = pass2_result.trend_note or hist.get("trend_note", "")
        summary_text = pass2_result.summary_text
        if mode == "pre_meal" and not meal_id:
            summary_text = self._sanitize_premeal_summary(summary_text)

        care_provider_view = None
        if audience == "care_provider":
            care_provider_view = CareProviderView(
                evidence_points=pass2_result.care_provider_evidence_points or [],
                metrics_table=pass2_result.care_provider_metrics_table or {
                    "current_meal": current,
                    "historical_comparison": hist,
                    "glycemic_response": gly or {},
                },
            )

        debug_payload = None
        if debug_enabled:
            historical = features.get("historical_comparison", {}) or {}
            debug_payload = {
                "anchor_date": evidence.get("anchor_date"),
                "source_flags": source_flags,
                "meal_reports_count": evidence.get("meal_reports_count", 0),
                "latest_meal_found": evidence.get("latest_meal_found"),
                "historical_cohort_size": historical.get("cohort_size", 0),
                "historical_cohort_selection": historical.get("cohort_selection"),
                "historical_deltas_keys": sorted(
                    list((historical.get("deltas_pct") or {}).keys())
                ),
                "fallback_used": (
                    "raw_fallback"
                    if source_flags.get("raw_fallback_used")
                    else "reports_primary"
                ),
                "warnings_count": len(warnings),
            }

        return MealAgentResponseData(
            conversation_id=conversation_id,
            snapshot_id=uuid4(),
            summary_text=summary_text,
            scores=MealAgentScores(**scores),
            verdicts=MealAgentVerdicts(
                calories=verdicts.get("calories", "within"),
                carbs=verdicts.get("carbs", "within"),
                protein=verdicts.get("protein", "within"),
                fat=verdicts.get("fat", "within"),
                fiber=verdicts.get("fiber", "within"),
            ),
            historical_comparison=HistoricalComparison(
                window_days=14,
                cohort_type="same_meal_type_time_bucket",
                cohort_size=int(hist.get("cohort_size", 0)),
                deltas_pct=hist.get("deltas_pct", {}),
                trend_note=trend_note,
            ),
            glycemic_response=GlycemicResponse(**gly) if gly else None,
            next_best_actions=(pass2_result.next_best_actions or self._fallback_actions(features))[:3],
            data_used=DataUsedFlags(
                reports=source_flags.get("reports", False),
                raw_fallback_used=source_flags.get("raw_fallback_used", False),
                cgm=source_flags.get("cgm", False),
                smbg=source_flags.get("smbg", False),
                sleep=source_flags.get("sleep", False),
                fitness=source_flags.get("fitness", False),
                vitals=source_flags.get("vitals", False),
                qdrant=source_flags.get("qdrant", False),
            ),
            warnings=warnings,
            confidence=confidence,
            care_provider_view=care_provider_view,
            debug=debug_payload,
        )

    @with_postgres_session
    async def _persist_snapshot(
        self,
        payload: MealAgentRequest,
        conversation_id: str,
        mode: str,
        features: Dict[str, Any],
        evidence: Dict[str, Any],
        output: Dict[str, Any],
        pass1_json: Dict[str, Any],
        model_meta: Dict[str, Any],
        *,
        postgres_session: AsyncSession,
    ) -> UUID:
        snapshot = AgentMealSnapshot(
            patient_id=payload.patient_id,
            meal_id=payload.meal_id,
            conversation_id=conversation_id,
            audience=payload.audience,
            mode=mode,
            data_source_strategy="report_first_raw_fallback",
            features_json=features,
            evidence_json=evidence,
            output_json=output,
            pass1_json=pass1_json,
            model_meta_json=model_meta,
        )
        postgres_session.add(snapshot)
        await postgres_session.commit()
        await postgres_session.refresh(snapshot)
        return snapshot.snapshot_id

    async def _insert_message(
        self,
        conversation_id: str,
        patient_id: str,
        meal_id: Optional[str],
        audience: str,
        role: str,
        content: str,
        message_type: str,
        snapshot_id: Optional[str] = None,
    ) -> None:
        await self.agent_meal_messages_collection.insert_one(
            {
                "conversation_id": conversation_id,
                "patient_id": patient_id,
                "meal_id": meal_id,
                "audience": audience,
                "role": role,
                "content": content,
                "message_type": message_type,
                "snapshot_id": snapshot_id,
                "created_at": datetime.utcnow(),
            }
        )

    async def _fetch_recent_messages(self, conversation_id: str) -> List[MealAgentMessage]:
        cursor = self.agent_meal_messages_collection.find(
            {"conversation_id": conversation_id}
        ).sort("created_at", -1).limit(8)
        rows = await cursor.to_list(length=8)
        rows.reverse()
        return [
            MealAgentMessage(
                id=str(row["_id"]),
                conversation_id=row["conversation_id"],
                patient_id=row["patient_id"],
                meal_id=row.get("meal_id"),
                audience=row["audience"],
                role=row["role"],
                content=row["content"],
                message_type=row.get("message_type", "text"),
                snapshot_id=row.get("snapshot_id"),
                created_at=row.get("created_at", datetime.utcnow()),
            )
            for row in rows
        ]

    @staticmethod
    def _build_conversation_id(patient_id: UUID, meal_id: Optional[UUID]) -> str:
        if meal_id:
            return f"meal-agent:{patient_id}:meal:{meal_id}"
        return f"meal-agent:{patient_id}:general"

    @staticmethod
    def _resolve_mode(mode: str, meal_id: Optional[UUID]) -> str:
        if mode != "auto":
            return mode
        return "post_meal" if meal_id else "pre_meal"

    @staticmethod
    def _time_bucket(meal_time: time) -> str:
        hour = meal_time.hour
        if hour < 6:
            return "late_night"
        if hour < 10:
            return "breakfast_window"
        if hour < 15:
            return "lunch_window"
        if hour < 19:
            return "afternoon_window"
        if hour < 23:
            return "dinner_window"
        return "late_night"

    def _pick_meal_target(
        self,
        meal_type: str,
        diet_recommendation: Dict[str, Any],
    ) -> Dict[str, float]:
        is_snack = "snack" in (meal_type or "").lower()
        section = "snack" if is_snack else "major_meal"
        target = diet_recommendation.get(section) or {}
        return {
            "calories": float(target.get("calories", 0) or 0),
            "carbs": float(target.get("carbs", 0) or 0),
            "protein": float(target.get("protein", 0) or 0),
            "fat": float(target.get("fats", 0) or 0),
            "fiber": float(target.get("fiber", 0) or 0),
        }

    def _build_historical_comparison(
        self,
        current_meal: Dict[str, Any],
        meal_reports: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        cur_type = (current_meal.get("meal_type") or "").lower()
        if cur_type in {"", "unknown"}:
            cur_type = ""
        cur_bucket = current_meal.get("time_bucket")

        strict_cohort = self._collect_report_cohort(
            meal_reports=meal_reports,
            meal_type=cur_type,
            time_bucket=cur_bucket,
        )
        if strict_cohort:
            cohort = strict_cohort
            cohort_selection = "strict_type_time_bucket"
        else:
            type_only_cohort = self._collect_report_cohort(
                meal_reports=meal_reports,
                meal_type=cur_type,
                time_bucket=None,
            )
            if type_only_cohort:
                cohort = type_only_cohort
                cohort_selection = "type_only"
            else:
                cohort = self._collect_report_cohort(
                    meal_reports=meal_reports,
                    meal_type=None,
                    time_bucket=None,
                )
                cohort_selection = "all_meals"

        if not cohort:
            return {
                "cohort_size": 0,
                "deltas_pct": {},
                "trend_note": "Insufficient historical cohort for direct comparison.",
                "cohort_selection": "none",
            }

        med = {
            "calories": median([row["calories"] for row in cohort]),
            "carbs": median([row["carbs"] for row in cohort]),
            "protein": median([row["protein"] for row in cohort]),
            "fat": median([row["fat"] for row in cohort]),
            "fiber": median([row["fiber"] for row in cohort]),
        }

        deltas = {}
        for key, base in med.items():
            current_val = float(current_meal.get(key) or 0)
            if base <= 0:
                deltas[f"{key}_delta_pct"] = 0.0
                continue
            deltas[f"{key}_delta_pct"] = round((current_val - base) * 100 / base, 2)

        trend_note = (
            "Compared with the last 14-day similar meals, this meal is "
            f"{'higher' if deltas.get('carbs_delta_pct', 0) > 0 else 'lower'} in carbs "
            f"and {'higher' if deltas.get('fiber_delta_pct', 0) > 0 else 'lower'} in fiber."
        )
        return {
            "cohort_size": len(cohort),
            "deltas_pct": deltas,
            "trend_note": trend_note,
            "cohort_selection": cohort_selection,
        }

    def _collect_report_cohort(
        self,
        meal_reports: List[Dict[str, Any]],
        meal_type: Optional[str],
        time_bucket: Optional[str],
    ) -> List[Dict[str, float]]:
        cohort: List[Dict[str, float]] = []
        for report in meal_reports:
            meals = report.get("meals", []) or []
            for meal in meals:
                item_type = (meal.get("type") or "").lower()
                meal_time = self._parse_time_safe(str(meal.get("time", "")))
                if meal_type and item_type != meal_type:
                    continue
                if (
                    time_bucket
                    and meal_time
                    and self._time_bucket(meal_time) != time_bucket
                ):
                    continue
                macros = meal.get("total_macro_nutritional_value", {}) or {}
                cohort.append(
                    {
                        "calories": float(macros.get("calories") or 0),
                        "carbs": float(macros.get("carbohydrates") or 0),
                        "protein": float(macros.get("proteins") or 0),
                        "fat": float(macros.get("fats") or 0),
                        "fiber": float(macros.get("fiber") or 0),
                    }
                )
        return cohort

    @staticmethod
    def _select_latest_meal_from_reports(
        meal_reports: List[Dict[str, Any]],
    ) -> tuple[Optional[Dict[str, Any]], Optional[date]]:
        latest: Optional[Dict[str, Any]] = None
        latest_dt: Optional[datetime] = None
        latest_date: Optional[date] = None
        for report in meal_reports:
            report_date = AgentMealV1Service._extract_report_date(report)
            for meal in report.get("meals", []) or []:
                meal_time = str(meal.get("time", ""))
                parsed_dt = AgentMealV1Service._parse_meal_datetime(
                    report_date=report_date,
                    meal_time=meal_time,
                )
                if not parsed_dt:
                    continue
                if latest_dt is None or parsed_dt > latest_dt:
                    latest_dt = parsed_dt
                    latest = meal
                    latest_date = parsed_dt.date()
        return latest, latest_date

    @staticmethod
    def _extract_report_date(report: Dict[str, Any]) -> str:
        if report.get("date"):
            return str(report["date"])
        metadata = report.get("metadata", {}) or {}
        date_range = metadata.get("date_range", {}) or {}
        start = str(date_range.get("start", ""))
        if "T" in start:
            return start.split("T")[0]
        return start

    @staticmethod
    def _parse_meal_datetime(report_date: str, meal_time: str) -> Optional[datetime]:
        time_formats = ("%H:%M:%S", "%H:%M")
        for fmt in time_formats:
            try:
                parsed_time = datetime.strptime(meal_time, fmt).time()
                return datetime.combine(date.fromisoformat(report_date), parsed_time)
            except Exception:
                continue
        return None

    @staticmethod
    def _infer_meal_type_from_bucket(time_bucket: str) -> str:
        if time_bucket == "breakfast_window":
            return "breakfast"
        if time_bucket == "lunch_window":
            return "lunch"
        if time_bucket == "dinner_window":
            return "dinner"
        return "snack"

    def _build_verdicts(
        self,
        current_meal: Dict[str, Any],
        target: Dict[str, float],
    ) -> Dict[str, str]:
        return {
            "calories": self._single_verdict(current_meal.get("calories", 0), target.get("calories", 0)),
            "carbs": self._single_verdict(current_meal.get("carbs", 0), target.get("carbs", 0)),
            "protein": self._single_verdict(current_meal.get("protein", 0), target.get("protein", 0)),
            "fat": self._single_verdict(current_meal.get("fat", 0), target.get("fat", 0)),
            "fiber": self._single_verdict(current_meal.get("fiber", 0), target.get("fiber", 0)),
        }

    @staticmethod
    def _single_verdict(value: float, target: float) -> str:
        val = float(value or 0)
        tgt = float(target or 0)
        if tgt <= 0:
            return "within"
        lower = tgt * 0.9
        upper = tgt * 1.1
        if val < lower:
            return "under"
        if val > upper:
            return "over"
        return "within"

    @staticmethod
    def _normalize_glucose_series(
        values: List[Any],
    ) -> List[tuple[datetime, float]]:
        parsed: List[tuple[datetime, float]] = []
        for item in values:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                ts, val = item[0], item[1]
            elif isinstance(item, dict):
                ts = item.get("device_timestamp") or item.get("timestamp")
                val = item.get("glucose_mgdl") or item.get("value")
            else:
                continue

            try:
                ts_parsed = (
                    datetime.fromisoformat(str(ts))
                    if not isinstance(ts, datetime)
                    else ts
                )
                parsed.append((ts_parsed, float(val)))
            except Exception:
                continue
        return parsed

    @staticmethod
    def _parse_time_safe(time_str: str) -> Optional[time]:
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(time_str, fmt).time()
            except ValueError:
                continue
        return None

    @staticmethod
    def _compute_scores(
        features: Dict[str, Any],
        source_flags: Dict[str, bool],
    ) -> Dict[str, float]:
        verdicts = features.get("verdicts", {})
        adherence_base = 10.0
        for key in ("calories", "carbs", "protein", "fat", "fiber"):
            if verdicts.get(key) != "within":
                adherence_base -= 1.2
        adherence = max(1.0, round(adherence_base, 2))

        gly = features.get("glycemic_response", {}) or {}
        delta = gly.get("delta_mgdl")
        if delta is None:
            glucose_impact = 6.0 if source_flags.get("cgm") else 5.0
        elif delta <= 30:
            glucose_impact = 9.0
        elif delta <= 60:
            glucose_impact = 7.0
        elif delta <= 90:
            glucose_impact = 5.5
        else:
            glucose_impact = 4.0

        overall = round((adherence * 0.55) + (glucose_impact * 0.45), 2)
        return {
            "overall": round(max(1.0, min(10.0, overall)), 2),
            "glucose_impact": round(max(1.0, min(10.0, glucose_impact)), 2),
            "adherence": round(max(1.0, min(10.0, adherence)), 2),
        }

    @staticmethod
    def _compute_confidence(
        source_flags: Dict[str, bool],
        warnings: List[str],
    ) -> float:
        base = 0.45
        for key in ("reports", "cgm", "smbg", "sleep", "fitness", "vitals", "qdrant"):
            if source_flags.get(key):
                base += 0.07
        if source_flags.get("raw_fallback_used"):
            base -= 0.04
        base -= min(len(warnings) * 0.03, 0.2)
        return round(max(0.1, min(0.98, base)), 2)

    @staticmethod
    def _fallback_actions(features: Dict[str, Any]) -> List[str]:
        verdicts = features.get("verdicts", {})
        actions = []
        if verdicts.get("carbs") == "over":
            actions.append("Reduce carb portion by 20% in the next similar meal.")
        if verdicts.get("protein") == "under":
            actions.append("Add a lean protein source to improve satiety and balance.")
        if verdicts.get("fiber") == "under":
            actions.append("Include one high-fiber side such as salad or legumes.")
        if not actions:
            actions.append("Keep this pattern and maintain consistent portions.")
        return actions[:3]

    @staticmethod
    def _build_model_meta() -> Dict[str, Any]:
        return {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "flow": "two_pass_bounded",
            "created_at": datetime.utcnow().isoformat(),
        }

    @staticmethod
    def _sanitize_premeal_summary(summary_text: str) -> str:
        sanitized = summary_text.replace("current meal", "recent meal pattern")
        sanitized = sanitized.replace("this meal", "your upcoming meal choice")
        sanitized = sanitized.replace("you ate", "you typically eat")
        return sanitized
