import json
from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from fastapi import status
from fastapi.exceptions import HTTPException
from sqlalchemy import asc, delete, desc, func
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
from lib.schemas.patient_meal import MealAnalysisResponse
from lib.schemas.patient_meal import PatientMeal as PatientMealSchema
from lib.services.ai_conversation_service.ai_conversation_service import (
    AiConversationService,
)
from lib.services.vector import MealVectorService
from lib.services.patient_profile_service import PatientProfileService
from lib.workers.tasks.meal.enqueue import enqueue_daily_meal_report_sync
from lib.utils.http_exceptions import raise_http_exception
from lib.utils.postgres_session_decorator import with_postgres_session
from rest_server.patients.meals.api_schema import (
    PatientMealUpdateRequest,
    PatientMealUploadRequest,
)

from .analysis import MealAnalysisService
from .helpers import (
    create_food_item,
    generate_conversation_flow,
    trigger_meal_tasks,
)


class MealService:
    """Main meal service that orchestrates meal operations."""

    CARB_SPLIT_TOLERANCE = 1.0

    def __init__(
        self,
        postgres_store: PostgresStore,
        meal_analysis_service: MealAnalysisService,
        patient_profile_service: PatientProfileService,
        meal_vector_service: MealVectorService,
    ):
        self.postgres_store = postgres_store
        self.meal_analysis_service = meal_analysis_service
        self.patient_profile_service = patient_profile_service
        self.meal_vector_service = meal_vector_service
        self.ai_conversation_service = AiConversationService(
            conversation_type="meal",
            selected_ai_model="gpt-4.1-mini",
            ai_model_provider="openai",
        )

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
    async def upload_meal(
        self,
        meal_data: PatientMealUploadRequest,
        patient_id: str,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        try:
            meal = PatientMealModel(
                type=meal_data.type,
                time=meal_data.datetime.time(),
                date=meal_data.datetime.date(),
                source=meal_data.source,
                description=meal_data.description,
                image_url=(str(meal_data.image_url) if meal_data.image_url else None),
                patient_id=patient_id,
            )

            postgres_session.add(meal)
            await postgres_session.commit()
            await postgres_session.refresh(meal)

            enqueue_daily_meal_report_sync(str(patient_id), meal.date)

            # Gamification hook (fire-and-forget)
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler.on_meal_logged(_UUID(patient_id))
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

            meal.type = update_data.type
            meal.time = update_data.datetime.time()
            meal.date = update_data.datetime.date()
            meal.source = update_data.source
            if update_data.description is not None:
                meal.description = update_data.description
            if update_data.image_url is not None:
                meal.image_url = (
                    str(update_data.image_url) if update_data.image_url else None
                )

            meal.analyzed = False
            meal.analyzed_at = None
            meal.score = None
            meal.feedback = None
            meal.tags = None

            for item in meal.items:
                await postgres_session.delete(item)

            if meal.total_macro_nutritional_value:
                await postgres_session.delete(meal.total_macro_nutritional_value)
            if meal.total_micro_nutritional_value:
                await postgres_session.delete(meal.total_micro_nutritional_value)

            await postgres_session.commit()
            await postgres_session.refresh(meal)

            enqueue_daily_meal_report_sync(str(patient_id), meal.date)

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
    async def analyze_or_reanalyze_meal(
        self,
        meal_id: str,
        patient_id: str,
        re_analyze: Optional[bool] = False,
        update_fields: Optional[dict] = None,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        try:
            meal = await self.fetch_meal(meal_id, postgres_session=postgres_session)
            meal_orm = PatientMealSchema.model_validate(meal)

            if meal_orm.analyzed and not re_analyze:
                return meal

            parsed_ai_response = await self._perform_meal_analysis(
                meal, meal_orm, patient_id, update_fields
            )

            if not parsed_ai_response:
                raise_http_exception(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    message=f"Meal with ID {meal_id} failed to be analyzed",
                )

            updated_meal = await self.save_meal_analysis(
                meal, parsed_ai_response, postgres_session=postgres_session
            )

            if re_analyze:
                await self.ai_conversation_service.delete_conversation_messages(
                    conversation_id=meal_id
                )

            await self._create_meal_conversation(meal_orm, meal_id, parsed_ai_response)
            trigger_meal_tasks(str(patient_id), str(meal_id), meal.date, updated_meal)

            # Refresh macro task progress (nutritional values changed after analysis)
            try:
                from uuid import UUID as _UUID
                from lib.core.container import container
                from lib.services.gamification.event_handler import GamificationEventHandler
                handler = container.resolve(GamificationEventHandler)
                await handler._refresh_macro_progress(_UUID(patient_id))
            except Exception:
                pass

            return updated_meal
        except (json.JSONDecodeError, SQLAlchemyError) as e:
            await postgres_session.rollback()
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if isinstance(e, json.JSONDecodeError)
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            raise_http_exception(
                status_code=status_code,
                message="Invalid JSON"
                if isinstance(e, json.JSONDecodeError)
                else "Database Error",
                detail=str(e),
            )

    async def _perform_meal_analysis(
        self,
        meal: PatientMealModel,
        meal_orm: PatientMealSchema,
        patient_id: str,
        update_fields: Optional[dict],
    ) -> MealAnalysisResponse:
        if update_fields:
            if "description" in update_fields:
                meal.description = update_fields["description"]
            return await self.meal_analysis_service.reanalyze_meal(
                patient_id, meal_orm.model_dump(), update_fields
            )

        patient = await self.patient_profile_service.fetch_patient_profile(
            patient_id=patient_id, detailed=True
        )
        patient_profile_json = CorePatientProfile.from_orm(patient).model_dump()

        return await self.meal_analysis_service.analyze_meal(
            patient_id,
            patient_profile_json,
            meal.time,
            meal.image_url,
            meal.type,
            meal.description,
        )

    async def _create_meal_conversation(
        self,
        meal_orm: PatientMealSchema,
        meal_id: str,
        parsed_ai_response: MealAnalysisResponse,
    ):
        message_sequence = generate_conversation_flow(
            meal_orm, meal_id, parsed_ai_response
        )
        await self.ai_conversation_service.add_multiple_messages_to_conversation(
            messages=message_sequence,
        )

    @with_postgres_session
    async def save_meal_analysis(
        self,
        meal: Any,
        analysis_data: MealAnalysisResponse,
        *,
        postgres_session: AsyncSession,
    ) -> PatientMealModel:
        self._normalize_carb_distribution(analysis_data)

        meal.items = [
            create_food_item(meal, item_data) for item_data in analysis_data.items
        ]

        total_macro = analysis_data.total_macro_nutritional_value.model_dump()
        meal.total_macro_nutritional_value = PatientTotalMacroNutritionalValueModel(
            meal_id=meal.id, **total_macro
        )

        total_micro = analysis_data.total_micro_nutritional_value.model_dump()
        meal.total_micro_nutritional_value = PatientTotalMicroNutritionalValueModel(
            meal_id=meal.id, **total_micro
        )

        meal.name = analysis_data.meal_name
        meal.feedback = analysis_data.feedback
        meal.tags = analysis_data.tags
        meal.score = float(analysis_data.score)
        meal.analyzed = True
        meal.analyzed_at = datetime.now()

        await postgres_session.merge(meal)
        await postgres_session.commit()

        return meal

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
        try:
            meal = PatientMealModel(
                name=ext.name,
                type=request.slot.value,
                slot=request.slot.value,
                date=request.consumed_at.date(),
                time=request.consumed_at.time(),
                source=request.source.value,
                description=request.description,
                image_url=request.image_url,
                audio_url=request.audio_url,
                tags=ext.tags or [],
                analyzed=True,
                analyzed_at=datetime.now(),
                extraction_confidence=ext.overall_confidence.value,
                preview_trace_id=request.preview_trace_id,
                note=request.note,
                patient_id=patient_id,
            )
            _attach_items_and_totals(meal, ext)

            postgres_session.add(meal)
            await postgres_session.commit()
            await postgres_session.refresh(meal)

            trigger_meal_tasks(
                patient_id=str(patient_id),
                meal_id=str(meal.id),
                meal_date=meal.date,
                meal_obj=meal,
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
                            "slot": meal.slot or meal.type,
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
            meal.type = request.slot.value
            meal.slot = request.slot.value
            meal.date = request.consumed_at.date()
            meal.time = request.consumed_at.time()
            meal.source = request.source.value
            meal.description = request.description
            if request.image_url is not None:
                meal.image_url = request.image_url
            if request.audio_url is not None:
                meal.audio_url = request.audio_url
            meal.tags = list(ext.tags or [])
            meal.analyzed = True
            meal.analyzed_at = datetime.now()
            meal.extraction_confidence = ext.overall_confidence.value
            if request.preview_trace_id is not None:
                meal.preview_trace_id = request.preview_trace_id
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

            trigger_meal_tasks(
                patient_id=str(patient_id),
                meal_id=str(meal.id),
                meal_date=meal.date,
                meal_obj=meal,
            )
            if old_date != meal.date:
                try:
                    enqueue_daily_meal_report_sync(str(patient_id), old_date)
                except Exception:
                    pass

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

    @classmethod
    def _normalize_carb_distribution(
        cls, analysis_data: MealAnalysisResponse
    ) -> None:
        cls._normalize_macro_values(analysis_data.total_macro_nutritional_value)
        for item in analysis_data.items:
            cls._normalize_macro_values(item.macro_nutritional_values)

    @classmethod
    def _normalize_macro_values(cls, macro_values: Any) -> None:
        total_carbs = getattr(macro_values, "carbohydrates", None)
        simple_carbs = getattr(macro_values, "simple_carbs", None)
        complex_carbs = getattr(macro_values, "complex_carbs", None)

        if total_carbs is None or total_carbs < 0:
            macro_values.simple_carbs = None
            macro_values.complex_carbs = None
            return

        if simple_carbs is None and complex_carbs is None:
            macro_values.simple_carbs = None
            macro_values.complex_carbs = None
            return

        if simple_carbs is not None and simple_carbs < 0:
            simple_carbs = None
        if complex_carbs is not None and complex_carbs < 0:
            complex_carbs = None

        if simple_carbs is None and complex_carbs is None:
            macro_values.simple_carbs = None
            macro_values.complex_carbs = None
            return

        if simple_carbs is None:
            inferred_simple = total_carbs - complex_carbs
            if inferred_simple < 0:
                macro_values.simple_carbs = None
                macro_values.complex_carbs = None
                return
            simple_carbs = inferred_simple

        if complex_carbs is None:
            inferred_complex = total_carbs - simple_carbs
            if inferred_complex < 0:
                macro_values.simple_carbs = None
                macro_values.complex_carbs = None
                return
            complex_carbs = inferred_complex

        split_sum = simple_carbs + complex_carbs

        if split_sum < 0:
            macro_values.simple_carbs = None
            macro_values.complex_carbs = None
            return

        if split_sum == 0:
            if total_carbs == 0:
                macro_values.simple_carbs = 0.0
                macro_values.complex_carbs = 0.0
            else:
                macro_values.simple_carbs = None
                macro_values.complex_carbs = None
            return

        # Always normalize to total carbohydrates so AI mismatch does not
        # collapse distribution to null and sum remains consistent.
        scale = total_carbs / split_sum
        simple_carbs = simple_carbs * scale
        complex_carbs = complex_carbs * scale

        macro_values.simple_carbs = round(simple_carbs, 2)
        macro_values.complex_carbs = round(complex_carbs, 2)

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

            enqueue_daily_meal_report_sync(str(patient_id), meal_date)
            await self.meal_vector_service.delete_meal_vector(str(meal_id))

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
