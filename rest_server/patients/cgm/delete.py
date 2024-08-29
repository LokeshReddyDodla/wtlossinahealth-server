from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
from typing import Union

router = APIRouter()


@router.delete("/clear/{table_name}", tags=["CGM"])
async def clear_all_data(
    table_name: str, request: Request
) -> Union[dict, HTTPException]:
    try:
        clickhouse_store = request.state.context.clickhouse_store
        clickhouse_store.clear_all_data(table_name)
        return {
            "message": f"All data for table '{table_name}' cleared successfully."
        }
    except Exception as e:
        response = {"message": "Internal Server Error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=response)
