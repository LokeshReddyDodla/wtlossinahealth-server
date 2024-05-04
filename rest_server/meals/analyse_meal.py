import json
from typing import Dict, Optional
from typing import Union

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request

from lib.core.auth_bearer import handler
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info


# Create FastAPI router
router = APIRouter(prefix="/meal")

    
@router.post(path="/analyse", tags=["Meal"])
async def analyse_meal(
    request: Request,
    image_url: str,
    description: Optional[str] = None,
    # user=handler,
) -> Union[Dict, HTTPException]:
    """
    Analyse Meal API
    """
    try:
        ai_response = get_nutritional_info(image_url, description)
        parsed_json = parse_json_garbage(ai_response)        
        
        return {"success": True, "food_description": parsed_json}
    except json.JSONDecodeError:
        return HTTPException(status_code=400, detail="Invalid JSON")
