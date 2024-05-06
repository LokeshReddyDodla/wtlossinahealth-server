from email import message
import json
from typing import Dict, Optional
from typing import Union

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse

from lib.core.auth_bearer import handler
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from rest_server.meals.api_schema import FoodDescription, MealAnalysisResponse
from rest_server.response_models import ErrorResponse, SuccessResponse


# Create FastAPI router
router = APIRouter(prefix="/meal")

    
@router.post(path="/analyse", response_model=MealAnalysisResponse, tags=["Meal"])
async def analyse_meal(
    request: Request,
    image_url: str,
    description: Optional[str] = None,
    # user=handler,
) -> Union[MealAnalysisResponse, HTTPException]:
    """
    Analyse Meal API
    """
    try:
        print('==> analysing meal...')
        ai_response = get_nutritional_info(image_url, description)
        print('==> ai response: %s' % ai_response)
        parsed_json = parse_json_garbage(ai_response)   
        print('==> parsed json: %s' % parsed_json)     
        
        food_description = FoodDescription(
            items=parsed_json["items"],
            total_nutritional_value=parsed_json["total_nutritional_value"],
            image_url=image_url,
            description=description,
        )
        
        return MealAnalysisResponse(data=food_description)
    
    except json.JSONDecodeError as e:
        response = ErrorResponse(message="Invalid JSON", detail=str(e))
        return JSONResponse(status_code=400, content=response.dict())
    
    except Exception as e:
        response = ErrorResponse(message="Internal Server Error", detail=str(e))
        return JSONResponse(status_code=500, content=response.dict())
