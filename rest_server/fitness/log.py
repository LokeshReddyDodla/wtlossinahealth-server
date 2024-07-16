import json
from datetime import datetime
from email import message
import os
from typing import Dict, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from lib.core.auth_bearer import handler
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from rest_server.meals.api_schema import MealDescription, MealAnalysisResponse
from rest_server.response_models import ErrorResponse, SuccessResponse


router = APIRouter(prefix="/fitness")

LOG_FILE_PATH = "fitness_log.json"

@router.post("/log", tags=["Fitness"])
async def log_fitness_data(request: Request):
    try:
        # Read the request body
        data = await request.json()
        
        # Append the data to the log file
        with open(LOG_FILE_PATH, "a") as log_file:
            json.dump(data, log_file)
            log_file.write("\n")  # Write each entry on a new line
                   
        response = SuccessResponse(message="Data logged successfully")
        return JSONResponse(status_code=200, content=response.dict())
    except Exception as e:
        response = ErrorResponse(message="Invalid JSON", detail=str(e))
        return JSONResponse(status_code=400, content=response.dict())
    
