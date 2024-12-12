import json
from typing import List, Union

from dateutil.parser import parse
from fastapi import (APIRouter, Depends, File, HTTPException, Request,
                     UploadFile, status)
from loguru import logger

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import ErrorResponse, SuccessResponse

from .router import router


@router.post("/dummy_upload", response_model=SuccessResponse)
async def upload_fitness_data(
    request: Request,
    file: UploadFile = File(...),
    current_patient: Patient = Depends(get_current_patient),
):
    try:
        # Read and parse the uploaded JSON file
        contents = await file.read()
        fitness_data = json.loads(contents)

        clickhouse_store = request.state.context.clickhouse_store

        # Prepare data to insert into ClickHouse
        data_points = []
        for item in fitness_data["fitness_data"]:
            data_points.append(
                {
                    "patient_id": str(current_patient.patient_id),
                    "type": item["type"],
                    "source": item["source"],
                    "unit": item["unit"],
                    "value": float(item["value"]),
                    "date_from": parse(item["date_from"])
                    .replace(tzinfo=None)
                    .strftime("%Y-%m-%dT%H:%M:%S"),
                    "date_to": parse(item["date_to"])
                    .replace(tzinfo=None)
                    .strftime("%Y-%m-%dT%H:%M:%S"),
                }
            )

        # Insert data into ClickHouse
        clickhouse_store.write_data("aihealth.fitness_data", data_points)

        return SuccessResponse(
            message="Fitness data uploaded and stored successfully.",
            data={"records_inserted": len(data_points)},
        )
    except Exception as e:
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
