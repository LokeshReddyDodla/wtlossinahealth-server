from fastapi import APIRouter, Request, HTTPException, Body
from lib.dependencies.auth.base import get_current_user
from pydantic import Json
from typing import Union
from loguru import logger
from fastapi import Depends

from rest_server.response_models import SuccessResponse

router = APIRouter()


@router.post(
    path="/dump",
    tags=["Data Dump"],
    response_model=SuccessResponse,
)
async def dump_data(
    request: Request,
    data: Union[Json, dict] = Body(...),
    current_user=Depends(get_current_user),
):
    """
    Dump raw data into MongoDB.
    """
    try:
        logger.info("Attempting to insert raw data into MongoDB")
        # Insert the raw data into the specified collection
        await request.state.context.mongo_store.insert_document(
            "raw_data_collection", data
        )
        logger.info("Data inserted successfully")
        return SuccessResponse(message="Data inserted successfully")
    except Exception as e:
        logger.error(f"Failed to insert data: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={"message": "Failed to insert data", "error": str(e)},
        )
