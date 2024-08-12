from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    File,
)
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session
from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import List, Union
import pandas as pd
from io import StringIO
from datetime import datetime

router = APIRouter(prefix="/fitness")


class FitnessDataPoint(BaseModel):
    type: str
    value: float
    dateFrom: str
    dateTo: str


class FitnessDataRequest(BaseModel):
    fitness_data: List[FitnessDataPoint]


@router.post("/upload", tags=["Fitness"])
async def upload_fitness_data(
    request: Request,
    body: FitnessDataRequest,
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    try:
        clickhouse_store = request.state.context.clickhouse_store
        fitness_data = body.fitness_data
        print("==> fitness_data: ", fitness_data)

        # Extract time range from the fitness data
        start_time = min(
            datetime.fromisoformat(item.dateFrom).strftime("%Y-%m-%d %H:%M:%S")
            for item in fitness_data
        )
        end_time = max(
            datetime.fromisoformat(item.dateTo).strftime("%Y-%m-%d %H:%M:%S")
            for item in fitness_data
)

        print("==> start_time: ", start_time)
        print("==> end_time: ", end_time)

        # Delete existing data for the patient in the time range
        clickhouse_store.delete_existing_fitness_data(
            "aihealth.fitness_data",
            current_patient.patient_id,
            start_time,
            end_time,
        )

        # Prepare data for ClickHouseDB
        data_points = []
        for item in fitness_data:
            data_points.append(
                {
                    "patient_id": str(current_patient.patient_id),
                    "type": item.type,
                    "value": float(item.value),
                    "date_from": datetime.fromisoformat(
                        item.dateFrom
                    ).strftime("%Y-%m-%dT%H:%M:%S"),
                    "date_to": datetime.fromisoformat(item.dateTo).strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    ),
                }
            )

        # Insert data into ClickHouse
        clickhouse_store.write_data("aihealth.fitness_data", data_points)

        return SuccessResponse(
            message="Fitness data uploaded and stored successfully."
        )

    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
