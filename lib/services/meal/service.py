import json
import logging
from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import status
from fastapi.exceptions import HTTPException
from sqlalchemy import asc, delete, desc, func, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from lib.core.postgres_store import PostgresStore
from lib.models.patient_meal import PatientFoodItem as PatientFoodItemModel
from lib.models.patient_meal import PatientMeal as PatientMealModel
from lib.models.patient_meal import (
    PatientMacroNutritionalValue as PatientMacroNutritionalValueModel,
)
from lib.models.patient_meal import (
    PatientMicroNutritionalValue as PatientMicroNutritionalValueModel,
)
from lib.models.patient_meal import (
    PatientTotalMacroNutritionalValue as PatientTotalMacroNutritionalValueModel,
)
from lib.models.patient_meal import (
    PatientTotalMicroNutritionalValue as PatientTotalMicroNutritionalValueModel,
)
from lib.schemas.patient import CorePatientProfile
from lib.schemas.meal import MealCreateRequest

logger = logging.getLogger(__name__)
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.vector import MealVectorService
from lib.services.patient_profile_service import PatientProfileService
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from rest_server.patients.meals.api_schema import (
    PatientMealUpdateRequest,
)

from .helpers import (
    serialize_meal_for_vector,
    trigger_meal_tasks,
)


def _normalize_to_image_urls(
    image_url: object | None,
    image_urls: list | None,
) -> list[str] | None:
    """Merge legacy image_url + image_urls into a single list (source of truth)."""
    urls = [str(u) for u in (image_urls or [])]
    if image_url:
        s = str(image_url)
        if s not in urls:
            urls.insert(0, s)
    return urls or None


class MealService:
    """Main meal service that orchestrates meal operations."""

    CARB_SPLIT_TOLERANCE = 1.0

    def __init__(
        self,
        postgres_store: PostgresStore,
        patient_profile_service: PatientProfileService,
        meal_vector_service: MealVectorService,
    ):
        self.postgres_store = postgres_store
        self.patient_profile_service = patient_profile_service
        self.meal_vector_service = meal_vector_service

    @with_postgres_session
    async def fetch_meals(
        self,
        patient_id: str,
        start_datetime: Optional[datetime] = None,
        end_datetime: Optional[datetime] = None,
        source: Optional[str] = None,
        analyzed: Optional[str] = None,
        order_by: Optional[str] = "time",
        order: Optional[str] = "asc",
        limit: Optional[int] = None,
        *,
        postgres_session: AsyncSession,
    ):
        try:
            query = (
                select(PatientMealModel)
                .where(PatientMealModel.patient_id == patient_id)
                .options(
                    selectinload(PatientMealModel.items).selectinload(
                        PatientFoodItemModel.macro_nutritional_values
                    ),
                    selectinload(PatientMealModel.items).selectinload(
                        PatientFoodItemModel.micro_nutritional_values
                    ),
                    selectinload(PatientMealModel.total_macro_nutritional_value),
                    selectinload(PatientMealModel.total_micro_nutritional_value),
                )
            )

            if start_datetime:
                query = query.filter(
                    (PatientMealModel.date > start_datetime.date())
                    | (
                        (PatientMealModel.date == start_datetime.date())
                        & (PatientMealModel.time >= start_datetime.time())
                    )
                )
            if end_datetime:
                query = query.filter(
                    (PatientMealModel.date < end_datetime.date())
                    | (
                        (PatientMealModel.date == end_datetime.date())
                        & (PatientMealModel.time <= end_datetime.time())
                    )
                )

            if source:
                query = query.filter(PatientMealModel.source == source)
            if analyzed == "true":
                query = query.filter(PatientMealModel.analyzed.is_(True))
            elif analyzed == "false":
                query = query.filter(PatientMealModel.analyzed.is_(False))

            if order_by == "time":
                if order == "asc":
                    query = query.order_by(asc(PatientMealModel.time))
                else:
                    query = query.order_by(desc(PatientMealModel.time))
            elif order_by == "created_at":
                if order == "asc":
                    query = query.order_by(asc(PatientMealModel.uploaded_at))
                else:
                    query = query.order_by(desc(PatientMealModel.uploaded_at))

            if limit:
                query = query.limit(limit)

            result = await postgres_session.execute(query)
            return result.scalars().all()
        except Exception as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Internal Server Error",
                detail=str(e),
            )

    @with_postgres_session
    async def fetch_meal(
        self, meal_id: str, *, postgres_session: AsyncSession
    ) -> PatientMealModel:
        query = (
            select(PatientMealModel)
            .where(PatientMealModel.id == meal_id)
            .options(
                selectinload(PatientMealModel.items).selectinload(
                    PatientFoodItemModel.macro_nutritional_values
                ),
                selectinload(PatientMealModel.items).selectinload(
                    PatientFoodItemModel.micro_nutritional_values
                ),
                selectinload(PatientMealModel.total_macro_nutritional_value),
                selectinload(PatientMealModel.total_micro_nutritional_value),
            )
        )

        result = await postgres_session.execute(query)
        meal = result.scalars().first()

        if not meal:
            raise_http_exception(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Meal not found",
            )

        return meal

    @with_postgres_session
    async def store_meal_analysis(
        self, meal_id: str, analysis: dict, *, postgres_session: AsyncSession
    ) -> int:
        """Persist the server-computed meal-analysis snapshot. Returns rows hit
        (0 if the meal was deleted before the analysis job ran)."""
        score = (analysis.get("score") or {}).get("overall")
        result = await postgres_session.execute(
            update(PatientMealModel)
            .where(PatientMealModel.id == meal_id)
            .values(meal_analysis=analysis, score=score)
        )
        await postgres_session.commit()
        return result.rowcount

    @with_postgres_session
    async def get_meal_vector_data(
        self, meal_id: str, *, postgres_session: AsyncSession
    ) -> dict | None:
        """Serialize a meal into the Qdrant vector payload, macros included.

        Reads Postgres (source of truth) with macro/micro relationships
        eager-loaded, so the vector can never drift from the report. Returns
        None when the meal no longer exists (deleted before the worker ran).
        """
        query = (
            select(PatientMealModel)
            .where(PatientMealModel.id == meal_id)
            .options(
                selectinload(PatientMealModel.items).selectinload(
                    PatientFoodItemModel.macro_nutritional_values
                ),
                selectinload(PatientMealModel.items).selectinload(
                    PatientFoodItemModel.micro_nutritional_values
                ),
                selectinload(PatientMealModel.total_macro_nutritional_value),
                selectinload(PatientMealModel.total_micro_nutritional_value),
            )
        )
        meal = (await postgres_session.execute(query)).scalars().first()
        if meal is None:
            return None
        return serialize_meal_for_vector(meal)

    @with_postgres_session
    async def get_meal_counts_by_date(
        self,
        patient_id: str,
        start_date: date,
        end_date: date,
        *,
        postgres_session: AsyncSession,
    ) -> List[dict]:
        try:
            query = (
                select(
                    PatientMealModel.date,
                    func.count(PatientMealModel.id).label("meal_count"),
                )
                .where(
                    PatientMealModel.patient_id == patient_id,
                    PatientMealModel.date >= start_date,
                    PatientMealModel.date <= end_date,
                )
                .group_by(PatientMealModel.date)
                .order_by(PatientMealModel.date)
            )

            result = await postgres_session.execute(query)
            records = result.all()

            return [
                {
                    "date": record.date.isoformat(),
                    "meal_count": record.meal_count,
                }
                for record in records
            ]

        except SQLAlchemyError as e:
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def update_meal(
        self,
        meal_id: str,
        update_data: PatientMealUpdateRequest,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        try:
            meal = await self.fetch_meal(meal_id, postgres_session=postgres_session)

            meal.slot = update_data.type
            meal.time = update_data.datetime.time()
            meal.date = update_data.datetime.date()
            meal.source = update_data.source
            if update_data.description is not None:
                meal.description = update_data.description
            if update_data.image_url is not None or update_data.image_urls is not None:
                meal.image_urls = _normalize_to_image_urls(
                    update_data.image_url, update_data.image_urls,
                )

            meal.analyzed = False
            meal.analyzed_at = None
            meal.score = None
            meal.tags = None

            for item in meal.items:
                await postgres_session.delete(item)

            if meal.total_macro_nutritional_value:
                await postgres_session.delete(meal.total_macro_nutritional_value)
            if meal.total_micro_nutritional_value:
                await postgres_session.delete(meal.total_micro_nutritional_value)

            await postgres_session.commit()
            await postgres_session.refresh(meal)

            # Re-upsert the Qdrant point (deterministic id → overwrite):
            # every write path that changes a meal must refresh its vector,
            # or the agent keeps citing the pre-edit meal.
            await trigger_meal_tasks(
                patient_id=str(patient_id),
                meal_id=str(meal.id),
                meal_date=meal.date,
            )

            # Refresh macro task progress (totals changed)
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler._refresh_macro_progress(_UUID(patient_id))
            except Exception:
                pass

            return meal

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def save_from_preview(
        self,
        patient_id: str,
        request: "MealCreateRequest",
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        """Persist a meal from a confirmed MealAnalysisResult extraction.

        No AI enrichment happens here. This is the 'dumb save' path —
        the intelligence already ran in the preview agent.
        """
        ext = request.extraction
        # Client-supplied analysis (from insights) is stored as-is and skips the
        # background job — no re-run, no drift from what the user saw.
        client_analysis = request.analysis or None
        try:
            meal = PatientMealModel(
                name=ext.name,
                slot=request.slot.value,
                date=request.consumed_at.date(),
                time=request.consumed_at.time(),
                source=request.source.value,
                description=request.description,
                image_urls=_normalize_to_image_urls(request.image_url, request.image_urls),
                audio_url=request.audio_url,
                tags=ext.tags or [],
                analyzed=True,
                analyzed_at=datetime.now(),
                preview_trace_id=request.preview_trace_id,
                meal_analysis=client_analysis,
                note=request.note,
                patient_id=patient_id,
            )
            _attach_items_and_totals(meal, ext)

            postgres_session.add(meal)
            await postgres_session.commit()
            await postgres_session.refresh(meal)

            await trigger_meal_tasks(
                patient_id=str(patient_id),
                meal_id=str(meal.id),
                meal_date=meal.date,
                run_analysis=client_analysis is None,
            )

            # EventBus publish — gamification and any future subscribers
            # react from here.
            try:
                from lib.ai_foundation.events.bus import EventBus
                from lib.ai_foundation.events.schemas import (
                    HealthEvent,
                    HealthEventType,
                )
                from lib.core.container import container

                bus = container.resolve(EventBus)
                await bus.publish(
                    HealthEvent(
                        event_type=HealthEventType.MEAL_LOGGED.value,
                        patient_id=str(patient_id),
                        data={
                            "meal_id": str(meal.id),
                            "slot": meal.slot,
                            "consumed_at": datetime.combine(
                                meal.date, meal.time
                            ).isoformat(),
                            "source": meal.source,
                        },
                        source_agent="meal_analysis",
                    )
                )
            except Exception:
                pass

            return meal
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def update_from_preview(
        self,
        patient_id: str,
        meal_id: str,
        request: "MealCreateRequest",
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        """Update an existing meal in place from a confirmed preview.

        Preserves ``meal_id`` so client references stay valid. Single
        transaction: updates top-level fields, replaces items + totals,
        commits. Background tasks re-upsert the Qdrant point (same
        deterministic point id) and regenerate the daily report. The
        MEAL_LOGGED event is NOT re-fired — it already fired on the
        first save; updates only refresh gamification's macro progress.
        """
        try:
            meal = await self.fetch_meal(meal_id, postgres_session=postgres_session)

            if str(meal.patient_id) != str(patient_id):
                raise_http_exception(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message="Meal does not belong to this patient.",
                )

            old_date = meal.date
            ext = request.extraction

            meal.name = ext.name
            meal.slot = request.slot.value
            meal.date = request.consumed_at.date()
            meal.time = request.consumed_at.time()
            meal.source = request.source.value
            meal.description = request.description
            if request.image_url is not None or request.image_urls is not None:
                meal.image_urls = _normalize_to_image_urls(
                    request.image_url, request.image_urls,
                )
            if request.audio_url is not None:
                meal.audio_url = request.audio_url
            meal.tags = list(ext.tags or [])
            meal.analyzed = True
            meal.analyzed_at = datetime.now()
            if request.preview_trace_id is not None:
                meal.preview_trace_id = request.preview_trace_id
            # Left untouched when the client sends none, so the report keeps the
            # prior snapshot until the background job recomputes it.
            client_analysis = request.analysis or None
            if client_analysis is not None:
                meal.meal_analysis = client_analysis
            if request.note is not None:
                meal.note = request.note

            for item in list(meal.items):
                await postgres_session.delete(item)
            if meal.total_macro_nutritional_value:
                await postgres_session.delete(meal.total_macro_nutritional_value)
            if meal.total_micro_nutritional_value:
                await postgres_session.delete(meal.total_micro_nutritional_value)
            await postgres_session.flush()

            _attach_items_and_totals(meal, ext)

            await postgres_session.commit()
            await postgres_session.refresh(meal)

            await trigger_meal_tasks(
                patient_id=str(patient_id),
                meal_id=str(meal.id),
                meal_date=meal.date,
                run_analysis=client_analysis is None,
            )
            if old_date != meal.date:
                from lib.derived import DataDomain, mark_dirty

                await mark_dirty(str(patient_id), DataDomain.MEAL, [old_date])

            # Gamification: macros changed, totals need refresh. Do NOT
            # re-fire MEAL_LOGGED — would duplicate XP / task completion.
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import (
                    GamificationEventHandler,
                )

                handler = container.resolve(GamificationEventHandler)
                await handler._refresh_macro_progress(_UUID(patient_id))
            except Exception:
                pass

            return meal
        except HTTPException:
            raise
        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_meal(
        self, meal_id: UUID, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            meal = await self.fetch_meal(
                str(meal_id), postgres_session=postgres_session
            )
            meal_date = meal.date

            await postgres_session.delete(meal)
            await postgres_session.commit()

            from lib.derived import DataDomain, mark_dirty

            await mark_dirty(str(patient_id), DataDomain.MEAL, [meal_date])
            try:
                await self.meal_vector_service.delete_meal_vector(str(meal_id))
            except Exception:
                # PG row is already gone — an orphaned Qdrant point would be
                # cited by the agent forever. Hand cleanup to a retryable job.
                logger.exception("Inline vector delete failed for meal %s — enqueuing retry", meal_id)
                from lib.workers.arq.redis import enqueue_job

                await enqueue_job(
                    "delete_meal_vector_task", str(meal_id),
                    _job_id=f"meal:vector:delete:{meal_id}",
                )

            # Clean up linked proactive insights
            try:
                from lib.core.container import container
                from lib.ai_foundation.agents.proactive_monitor.insight_tracker import InsightTracker
                tracker = container.resolve(InsightTracker)
                await tracker.delete_by_entity("meal", str(meal_id))
            except Exception:
                pass

            # Refresh macro task progress (totals decreased)
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler._refresh_macro_progress(_UUID(patient_id))
            except Exception:
                pass

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )

    @with_postgres_session
    async def delete_all_meals_for_patient(
        self, patient_id: str, *, postgres_session: AsyncSession
    ):
        try:
            await postgres_session.execute(
                delete(PatientMealModel).where(
                    PatientMealModel.patient_id == patient_id
                )
            )
            await postgres_session.commit()

            await self.meal_vector_service.delete_meal_vectors_for_patient(patient_id)

        except SQLAlchemyError as e:
            await postgres_session.rollback()
            raise_http_exception(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Database Error",
                detail=str(e),
            )


# ---------------------------------------------------------------------------
# Helpers shared by save_from_preview / update_from_preview
# ---------------------------------------------------------------------------


def _attach_items_and_totals(meal: PatientMealModel, ext: Any) -> None:
    """Build food items + total macro/micro rows and link them to ``meal``.

    ``ext`` is a MealExtraction (typed as Any here to avoid an import
    cycle). The caller commits and, on update paths, is responsible for
    deleting any pre-existing items before calling this.
    """
    food_items: List[PatientFoodItemModel] = []
    for it in ext.items:
        food_item = PatientFoodItemModel(
            name=it.name,
            center_point=it.center_point,
            serving_size=str(it.portion),
            serving_quantity=float(it.portion),
            serving_unit=it.unit,
            meal=meal,
        )
        food_item.macro_nutritional_values = PatientMacroNutritionalValueModel(
            food_item_id=food_item.id,
            calories=it.macros.calories,
            proteins=it.macros.protein,
            carbohydrates=it.macros.carbs,
            simple_carbs=it.macros.carbs_simple,
            complex_carbs=it.macros.carbs_complex,
            fats=it.macros.fat,
            fiber=it.macros.fiber,
        )
        food_item.micro_nutritional_values = PatientMicroNutritionalValueModel(
            food_item_id=food_item.id,
            calcium=it.micros.calcium_mg or 0,
            iron=it.micros.iron_mg or 0,
            zinc=it.micros.zinc_mg or 0,
            magnesium=it.micros.magnesium_mg or 0,
        )
        food_items.append(food_item)
    meal.items = food_items

    meal.total_macro_nutritional_value = PatientTotalMacroNutritionalValueModel(
        meal_id=meal.id,
        calories=ext.total_macros.calories,
        proteins=ext.total_macros.protein,
        carbohydrates=ext.total_macros.carbs,
        simple_carbs=ext.total_macros.carbs_simple,
        complex_carbs=ext.total_macros.carbs_complex,
        fats=ext.total_macros.fat,
        fiber=ext.total_macros.fiber,
    )
    meal.total_micro_nutritional_value = PatientTotalMicroNutritionalValueModel(
        meal_id=meal.id,
        calcium=ext.total_micros.calcium_mg or 0,
        iron=ext.total_micros.iron_mg or 0,
        zinc=ext.total_micros.zinc_mg or 0,
        magnesium=ext.total_micros.magnesium_mg or 0,
    )
