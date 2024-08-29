from io import StringIO
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    File,
    UploadFile,
)
from typing import Union

import pandas as pd

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from rest_server.response_models import ErrorResponse, SuccessResponse
from .router import router


@router.post("/upload", response_model=SuccessResponse)
async def upload_cgm_data(
    request: Request,
    file: UploadFile = File(...),
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    try:
        clickhouse_store = request.state.context.clickhouse_store

        # Read and parse the CSV file
        contents = await file.read()
        decoded = contents.decode("utf-8")

        # Skip metadata rows and set correct headers
        df = pd.read_csv(StringIO(decoded), skiprows=2)

        # Convert timestamps to the correct format without changing the timezone
        df["Device Timestamp"] = pd.to_datetime(
            df["Device Timestamp"], format="%d-%m-%Y %I:%M %p"
        )

        # Determine the time range of the new data
        start_time = df["Device Timestamp"].min()
        end_time = df["Device Timestamp"].max()

        # Delete existing data for the patient in the time range
        clickhouse_store.delete_existing_cgm_data(
            "aihealth.cgm_data",
            current_patient.patient_id,
            start_time,
            end_time,
        )

        # Prepare data for ClickHouseDB
        data_points = []
        for _, row in df.iterrows():
            if pd.notna(row["Scan Glucose mg/dL"]):
                record_type = "scan"
                glucose_level = int(row["Scan Glucose mg/dL"])
            elif pd.notna(row["Historic Glucose mg/dL"]):
                record_type = "historic"
                glucose_level = int(row["Historic Glucose mg/dL"])
            else:
                continue

            data_points.append(
                {
                    "patient_id": str(current_patient.patient_id),
                    "time": row["Device Timestamp"].strftime(
                        "%Y-%m-%dT%H:%M:%S"
                    ),
                    "glucose_level": glucose_level,
                    "record_type": record_type,
                }
            )

        # Insert data into ClickHouse
        clickhouse_store.write_data("aihealth.cgm_data", data_points)

        return SuccessResponse(
            message="CGM data uploaded and stored successfully."
        )

    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
