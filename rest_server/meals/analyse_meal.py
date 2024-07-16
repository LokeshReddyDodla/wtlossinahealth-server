import json
from typing import Optional, Union
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from lib.dependencies.auth import get_current_user
from lib.models.user import User
from lib.models.meal import (
    Meal,
    FoodItem,
    NutritionalValues,
    TotalNutritionalValue,
)
from lib.schemas.meal import FoodDescription
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from rest_server.meals.api_schema import MealAnalysisResponse
from rest_server.response_models import ErrorResponse
from lib.managers.context_manager import context_manager

# Create FastAPI router
router = APIRouter(prefix="/meal")


@router.post(
    path="/analyse", response_model=MealAnalysisResponse, tags=["Meal"]
)
async def analyse_meal_api(
    request: Request,
    image_url: str,
    mealtime_ms: int,
    description: Optional[str] = None,
    current_user: User = Depends(get_current_user),
) -> Union[MealAnalysisResponse, HTTPException]:
    """
    Analyse Meal API
    """
    async with request.state.context.postgres_store.get_session() as session:
        try:
            print("==> analysing meal...")
            print("==> image url: ", image_url)

            ai_response = get_nutritional_info(
                mealtime_ms, image_url, description
            )
            print("==> ai response: %s" % ai_response)

            parsed_json = parse_json_garbage(ai_response)
            print("==> parsed json: %s" % parsed_json)

            context_id = uuid.uuid4().hex

            # Create the meal entry
            meal = Meal(
                meal_type=parsed_json["meal_type"],
                image_url=image_url,
                description=description,
                feedback=parsed_json["feedback"],
                tags=parsed_json["tags"],
                context_id=context_id,
                user_id=current_user.user_id,
            )
            session.add(meal)
            await session.flush()  # Flush to get the meal ID

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

            # Create food items and their nutritional values
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

            await session.commit()

            # Prepare response
            food_description = FoodDescription(
                meal_type=parsed_json["meal_type"],
                items=parsed_json["items"],
                total_nutritional_value=parsed_json["total_nutritional_value"],
                image_url=image_url,
                description=description,
                feedback=parsed_json["feedback"],
                tags=parsed_json["tags"],
                context_id=context_id,
            )

            context_manager.add_message(
                context_id,
                ai_response,
                "assistant",
                "meal",
                media_url=image_url,
            )
            return MealAnalysisResponse(data=food_description)
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
