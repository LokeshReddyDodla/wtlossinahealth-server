from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
import logging

from lib.dependencies.database import get_postgres_session
from lib.models.patient_connected_app import PatientConnectedApp
from lib.services.file_content_extractor import FileContentExtractorService
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/test")

logger = logging.getLogger("mongo_test")

extractor = FileContentExtractorService()


@router.get(path="/mongodb", tags=["Test"])
async def test_api(request: Request):
    try:
        logger.info("Attempting to insert document")
        document = {"initial_key": "initial_value"}
        await request.state.context.mongo_store.insert_document(
            "test_collection", document
        )
        logger.info("Document inserted successfully")
        return {"message": "inserted successfully"}
    except Exception as e:
        logger.error(f"Failed to insert document: {str(e)}")
        return {"message": "failed to insert", "error": str(e)}


@router.post("/extract")
async def extract_file(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        text = extractor.extract(file_bytes, file.filename, file.content_type)
        return {"filename": file.filename, "content": text}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/libreview/never-synced")
async def patients_never_synced_libreview(
    session: AsyncSession = Depends(get_postgres_session),
):
    result = await session.execute(
        select(PatientConnectedApp).options(
            selectinload(PatientConnectedApp.libreview),
            selectinload(PatientConnectedApp.patient),
        )
    )
    connected_apps = result.scalars().all()

    never_synced_patients = []

    for app in connected_apps:
        libreview = app.libreview
        patient = app.patient
        if libreview and libreview.last_sync_timestamp is None:
            never_synced_patients.append(
                {
                    "patient_id": str(patient.patient_id),
                    "first_name": patient.first_name,
                    "last_name": patient.last_name,
                    "phone_number": patient.phone_number,
                    "email": patient.email,
                    "libreview_id": libreview.libreview_id,
                }
            )

    if not never_synced_patients:
        raise HTTPException(
            status_code=404,
            detail="No patients found with never-synced LibreView",
        )

    return {"patients": never_synced_patients}
