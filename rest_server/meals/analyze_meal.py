from datetime import datetime
import json
from typing import Optional, Union
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from lib.dependencies.auth import get_current_user
from lib.models.user import User
from lib.models.meal import (
    Meal,
    FoodItem,
    NutritionalValues,
    TotalNutritionalValue,
)
from lib.schemas.meal import MealResponse
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from rest_server.meals.api_schema import MealAnalysisResponse
from rest_server.response_models import ErrorResponse
from lib.managers.context_manager import context_manager
from sqlalchemy.orm import selectinload


# Create FastAPI router
router = APIRouter(prefix="/meal")


@router.post(path="/analyze", response_model=MealResponse, tags=["Meal"])
async def analyze_meal_api(
    request: Request,
    meal_id: str,
    force: Optional[bool] = False,
    current_user: User = Depends(get_current_user),
) -> Union[MealResponse, HTTPException]:
    """
    Analyse Meal API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            # Fetch the meal entry by ID
            meal_query = await session.execute(
                select(Meal)
                .filter(
                    Meal.id == meal_id, Meal.user_id == current_user.user_id
                )
                .options(
                    selectinload(Meal.items).selectinload(
                        FoodItem.nutritional_values
                    ),
                    selectinload(Meal.total_nutritional_value),
                )
            )
            meal = meal_query.scalars().first()

            if not meal:
                response = ErrorResponse(
                    message="Meal not found",
                    detail=f"Meal with ID {meal_id} not found",
                )
                raise HTTPException(status_code=404, detail=response.dict())

            if meal.analyzed and not force:
                return MealResponse.from_orm(meal)

            ai_response = get_nutritional_info(
                meal.time.timestamp(), meal.image_url, meal.description
            )
            print("==> ai response: %s" % ai_response)

            parsed_json = parse_json_garbage(ai_response)
            print("==> parsed json: %s" % parsed_json)

            # Update the meal entry
            meal.analyzed = True
            meal.analyzed_at = datetime.now()
            meal.feedback = parsed_json["feedback"]
            meal.tags = parsed_json["tags"]

            # Create total nutritional value entry
            total_nutritional_value = TotalNutritionalValue(
                calories=parsed_json["total_nutritional_value"]["calories"],
                proteins=parsed_json["total_nutritional_value"]["proteins"],
                carbohydrates=parsed_json["total_nutritional_value"][
                    "carbohydrates"
                ],
                fats=parsed_json["total_nutritional_value"]["fats"],
                fiber=parsed_json["total_nutritional_value"]["fiber"],
                meal_id=meal.id,
            )
            session.add(total_nutritional_value)
            meal.total_nutritional_value = total_nutritional_value

            # Create food items and their nutritional values
            food_items = []
            for item in parsed_json["items"]:
                food_item = FoodItem(
                    name=item["name"],
                    coordinates=item["coordinates"],
                    serving_size=item["serving_size"],
                    serving_quantity=item["serving_quantity"],
                    serving_unit=item["serving_unit"],
                    meal_id=meal.id,
                )
                session.add(food_item)
                await session.flush()  # Flush to get the food item ID

                nutritional_values = NutritionalValues(
                    calories=item["nutritional_values"]["calories"],
                    proteins=item["nutritional_values"]["proteins"],
                    carbohydrates=item["nutritional_values"]["carbohydrates"],
                    fats=item["nutritional_values"]["fats"],
                    fiber=item["nutritional_values"]["fiber"],
                    food_item_id=food_item.id,
                )
                session.add(nutritional_values)
                food_item.nutritional_values = nutritional_values

                food_items.append(food_item)

            meal.items = food_items

            await session.commit()

            context_manager.add_message(
                meal.context_id,
                ai_response or "",
                "assistant",
                "meal",
                media_url=meal.image_url,
            )

            meal_response = MealResponse.from_orm(meal)
            return meal_response
        except json.JSONDecodeError as e:
            await session.rollback()
            response = ErrorResponse(message="Invalid JSON", detail=str(e))
            raise HTTPException(status_code=400, detail=response.dict())

        except Exception as e:
            await session.rollback()
            response = ErrorResponse(
                message="Internal Server Error", detail=str(e)
            )
            raise HTTPException(status_code=400, detail=response.dict())
