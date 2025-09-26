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
from lib.dependencies.service_dependencies import (
    get_patient_connected_app_service,
)
from lib.models.patient_connected_app import PatientConnectedApp
from lib.services.file_content_extractor import FileContentExtractorService
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.services.patient_connected_app_service import (
    PatientConnectedAppService,
)
from lib.utils.http_exceptions import raise_http_exception
from rest_server.response_models import SuccessResponse
from fastapi import Depends, HTTPException, Query, Request, status


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


@router.delete(
    "/libreview/cleanup-invalid",
    response_model=SuccessResponse,
)
async def cleanup_invalid_libreview_connections(
    session: AsyncSession = Depends(get_postgres_session),
):
    try:
        result = await session.execute(
            select(PatientConnectedApp).options(
                selectinload(PatientConnectedApp.libreview),
                selectinload(PatientConnectedApp.patient),
            )
        )
        connected_apps = result.scalars().all()

        removed = []
        for app in connected_apps:
            libreview = app.libreview
            patient = app.patient
            if libreview and str(libreview.libreview_id) == str(
                patient.patient_id
            ):
                await session.delete(app)
                removed.append(
                    {
                        "patient_id": str(patient.patient_id),
                        "first_name": patient.first_name,
                        "last_name": patient.last_name,
                        "phone_number": patient.phone_number,
                        "email": patient.email,
                        "libreview_id": libreview.libreview_id,
                    }
                )

        if not removed:
            raise HTTPException(
                status_code=404,
                detail="No invalid LibreView connections found.",
            )

        await session.commit()

        return SuccessResponse(
            message=f"Removed {len(removed)} invalid LibreView connections.",
            data={"removed_patients": removed},
        )
    except HTTPException:
        raise
    except Exception as e:
        await session.rollback()
        raise_http_exception(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
            detail=str(e),
        )
