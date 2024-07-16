import json
from datetime import datetime
from email import message
from typing import Dict, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from lib.core.auth_bearer import handler
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from lib.utils.openai.prescription_analysis import analyse_prescription
from rest_server.meals.api_schema import MealDescription, MealAnalysisResponse
from rest_server.prescriptions.api_schema import Medicine, PrescriptionAnalysisResponse, PrescriptionData
from rest_server.response_models import ErrorResponse, SuccessResponse

# Create FastAPI router
router = APIRouter(prefix="/report")

    