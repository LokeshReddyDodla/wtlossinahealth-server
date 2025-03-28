from fastapi import APIRouter, Request
from fastapi.responses import Response

# Create FastAPI router
router = APIRouter(prefix="/system")


@router.get(path="/reload-cache", tags=["System"])
async def reload_cache(request: Request):
    """
    This API calls the cache manager to reload the cache
    """
    context = request.state.context
    await context.logger.info("Reload cache API")

    # Reload cache
    await context.logger.info("Cache reloaded successfully")

    return Response(status_code=200)
