from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    File,
)
from sqlalchemy.future import select
from sqlalchemy.orm import Session
from lib.models.admin import Admin
from lib.models.patient_connected_app import PatientConnectedApp
from lib.models.patient import Patient
from lib.dependencies.auth.admin_auth import get_current_admin
from rest_server.response_models import SuccessResponse, ErrorResponse
from typing import Union
import pandas as pd
from io import StringIO
from datetime import datetime
from sqlalchemy.orm import selectinload


router = APIRouter(prefix="/admin/patient")


@router.post("/cgm/upload", tags=["Admin Patient"])
async def admin_upload_cgm_data(
    request: Request,
    patient_id: str,
    file: UploadFile = File(...),
    current_admin: Admin = Depends(get_current_admin),
) -> Union[SuccessResponse, HTTPException]:
    try:
        clickhouse_store = request.state.context.clickhouse_store
        print("==> entered cgm/upload api...")
        print("==> patient_id: ", patient_id)

        # Fetch the patient from the database using patient_id
        async with request.state.context.postgres_store.get_session() as session:
            result = await session.execute(
                select(Patient).where(Patient.patient_id == patient_id)
            )
            patient = result.scalars().first()

            if not patient:
                raise HTTPException(
                    status_code=404, detail="Patient not found"
                )

            print("==> patient found!")
            # Read and parse the CSV file
            contents = await file.read()
            decoded = contents.decode("utf-8")

            # Skip metadata rows and set correct headers
            df = pd.read_csv(StringIO(decoded), skiprows=2)
            
            print("==> read csv")

            # Convert timestamps to the correct format without changing the timezone
            df["Device Timestamp"] = pd.to_datetime(
                df["Device Timestamp"], format="%d-%m-%Y %I:%M %p"
            )

            # Determine the time range of the new data
            start_time = df["Device Timestamp"].min()
            end_time = df["Device Timestamp"].max()
            
            print("==> got the start and end date ", start_time, end_time)

            # Delete existing data for the patient in the time range
            clickhouse_store.delete_existing_data(
                "aihealth.cgm_data",
                patient.patient_id,
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
                        "patient_id": str(patient.patient_id),
                        "time": row["Device Timestamp"].strftime(
                            "%Y-%m-%dT%H:%M:%S"
                        ),
                        "glucose_level": glucose_level,
                        "record_type": record_type,
                    }
                )

            print("==> inserting data...")
            # Insert data into ClickHouse
            clickhouse_store.write_data("aihealth.cgm_data", data_points)

            # Update last_sync_time in connected_apps -> libreview
            connected_app = await session.execute(
                select(PatientConnectedApp)
                .where(PatientConnectedApp.patient_id == patient.patient_id)
                .options(
                    selectinload(PatientConnectedApp.libreview),
                )
            )
            connected_app = connected_app.scalars().first()

            print("==> updated connected_apps")
            if connected_app and connected_app.libreview:
                connected_app.libreview.last_sync_timestamp = datetime.now()
                await session.commit()

            return SuccessResponse(
                message="CGM data uploaded and stored successfully."
            )

    except Exception as e:
        response = ErrorResponse(
            message="Internal Server Error", detail=str(e)
        )
        raise HTTPException(status_code=500, detail=response.dict())
