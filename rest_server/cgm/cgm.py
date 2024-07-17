import csv
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
from datetime import datetime

from influxdb_client import Point
import pandas as pd

from lib.dependencies.auth.patient_auth import get_current_patient
from lib.models.patient import Patient
from rest_server.response_models import ErrorResponse, SuccessResponse

# Create FastAPI router
router = APIRouter(prefix="/cgm")


@router.post("/upload", tags=["CGM"])
async def upload_cgm_data(
    request: Request,
    file: UploadFile = File(...),
    current_patient: Patient = Depends(get_current_patient),
) -> Union[SuccessResponse, HTTPException]:
    try:
        influx_store = request.state.context.influx_store

        # Read and parse the CSV file
        contents = await file.read()
        decoded = contents.decode("utf-8")

        # Skip metadata rows and set correct headers
        df = pd.read_csv(StringIO(decoded), skiprows=2)

        # Filter out rows where "Scan Glucose mg/dL" is empty
        df = df[df["Scan Glucose mg/dL"].notna()]

        # Convert timestamps to the correct format without changing the timezone
        df["Device Timestamp"] = pd.to_datetime(
            df["Device Timestamp"], format="%d-%m-%Y %I:%M %p"
        )

        # Prepare data for InfluxDB
        data_points = []
        uploaded_at = datetime.now().isoformat()
        for _, row in df.iterrows():
            point = (
                Point("cgm_data")
                .tag("patient_id", current_patient.patient_id)
                .tag("uploaded_at", uploaded_at)
                .time(row["Device Timestamp"].strftime("%Y-%m-%dT%H:%M:%S"))
                .field("scan_glucose_mg_dl", int(row["Scan Glucose mg/dL"]))
            )
            data_points.append(point)

        # Optionally delete existing data within the time range
        start_time = (
            df["Device Timestamp"].min().strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        end_time = df["Device Timestamp"].max().strftime("%Y-%m-%dT%H:%M:%SZ")

        influx_store.delete_data(
            measurement="cgm_data",
            start_time=start_time,
            end_time=end_time,
            tags={"patient_id": current_patient.patient_id},
        )

        # Write data to InfluxDB
        influx_store.write_data(data_points)

        return SuccessResponse(
            message="CGM data uploaded and stored successfully."
        )

    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())


@router.delete("/clear/{measurement}", tags=["CGM"])
async def clear_all_data(
    measurement: str, request: Request
) -> Union[dict, HTTPException]:
    try:
        influx_store = request.state.context.influx_store
        influx_store.clear_all_data(measurement)
        return {
            "message": f"All data for measurement '{measurement}' cleared successfully."
        }
    except Exception as e:
        response = {"message": "Internal Server Error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=response)
