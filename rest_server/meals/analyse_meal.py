import json
from datetime import datetime
from email import message
from typing import Dict, Optional, Union
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from lib.core.auth_bearer import handler
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from rest_server.meals.api_schema import FoodDescription, MealAnalysisResponse
from rest_server.response_models import ErrorResponse, SuccessResponse
from lib.managers.context_manager import context_manager

# Create FastAPI router
router = APIRouter(prefix="/meal")

    
@router.post(path="/analyse", response_model=MealAnalysisResponse, tags=["Meal"])
async def analyse_meal_api(
    request: Request,
    image_url: str,
    mealtime_ms: int,
    description: Optional[str] = None,
    # user=handler,
) -> Union[MealAnalysisResponse, HTTPException]:
    """
    Analyse Meal API
    """
    try:
        print('==> analysing meal...')
        print('==> image url: ', image_url)
        
        ai_response = get_nutritional_info(mealtime_ms, image_url, description)
        print('==> ai response: %s' % ai_response)
        
        parsed_json = parse_json_garbage(ai_response)   
        print('==> parsed json: %s' % parsed_json)     
        
        context_id = uuid.uuid4().hex
        
        food_description = FoodDescription(
            meal_type=parsed_json["meal_type"],
            items=parsed_json["items"],
            total_nutritional_value=parsed_json["total_nutritional_value"],
            image_url=image_url,
            description=description,
            feedback=parsed_json["feedback"],
            tags=parsed_json["tags"],
            context_id=context_id
        )
        
        context_manager.add_message(context_id, ai_response, "assistant", "meal", media_url=image_url)
        
        return MealAnalysisResponse(data=food_description)
    
    except json.JSONDecodeError as e:
        response = ErrorResponse(message="Invalid JSON", detail=str(e))
        return JSONResponse(status_code=400, content=response.dict())
    
    except Exception as e:
        response = ErrorResponse(message="Internal Server Error", detail=str(e))
        return JSONResponse(status_code=500, content=response.dict())
