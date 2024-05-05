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
from rest_server.meals.api_schema import MealAnalysisResponse
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
        ai_response = get_nutritional_info(image_url, description)
        parsed_json = parse_json_garbage(ai_response)        
        
        return SuccessResponse(data=parsed_json, message="Successfully analysed.")
    
    except json.JSONDecodeError as e:
        response = ErrorResponse(success=False, message="Invalid JSON", detail=str(e))
        return JSONResponse(status_code=400, content=response.dict())
    
    except Exception as e:
        response = ErrorResponse(success=False, message="Internal Server Error", detail=str(e))
        return JSONResponse(status_code=500, content=response.dict())
