import json
from datetime import datetime
from email import message
from typing import Dict, Optional, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from lib.core.auth_bearer import handler
from lib.utils.json_parsing import parse_json_garbage
from lib.utils.openai.meal_analysis import get_nutritional_info
from lib.utils.openai.prescription_analysis import analyze_prescription
from rest_server.meals.api_schema import MealDescription
from rest_server.prescriptions.api_schema import (
    Medicine,
    PrescriptionAnalysisResponse,
    PrescriptionData,
)
from rest_server.response_models import ErrorResponse, SuccessResponse

# Create FastAPI router
router = APIRouter(prefix="/prescription")


@router.post(path="/analyze", tags=["Prescription"])
async def analyze_prescription_api(
    request: Request,
    image_url: str,
    # user=handler,
) -> Union[PrescriptionAnalysisResponse, HTTPException]:
    """
    Analyze Prescription API
    """
    try:
        print("==> analysing prescription...")
        ai_response = analyze_prescription(image_url)
        print("==> ai response: %s" % ai_response)
        parsed_json = parse_json_garbage(ai_response)
        print("==> parsed json: %s" % parsed_json)

        if not parsed_json.get("prescription_valid"):
            raise HTTPException(
                status_code=400,
                detail=parsed_json.get(
                    "message", "Invalid prescription image"
                ),
            )

        prescription_data = PrescriptionData(
            prescription_valid=parsed_json["prescription_valid"],
            doctor_name=parsed_json.get("doctor_name"),
            patient_name=parsed_json.get("patient_name"),
            prescription_date=parsed_json.get("prescription_date"),
            medicines=[
                Medicine(**med) for med in parsed_json.get("medicines", [])
            ],
        )

        return PrescriptionAnalysisResponse(data=prescription_data)

    except json.JSONDecodeError as e:
        response = ErrorResponse(message="Invalid JSON", detail=str(e))
        return JSONResponse(status_code=400, content=response.dict())

    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        return JSONResponse(status_code=500, content=response.dict())
