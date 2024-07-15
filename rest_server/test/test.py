from fastapi import APIRouter, Request
import logging


router = APIRouter(prefix="/test")

logger = logging.getLogger("mongo_test")


@router.get(path="/", tags=["Test"])
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
