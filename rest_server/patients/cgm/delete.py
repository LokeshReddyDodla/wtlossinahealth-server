from typing import Union

from fastapi import APIRouter, HTTPException, Request

from rest_server.response_models import SuccessResponse

from .router import router


@router.delete("/clear/{table_name}", response_model=SuccessResponse)
async def clear_all_data(
    table_name: str, request: Request
):
    try:
        clickhouse_store = request.state.context.clickhouse_store
        clickhouse_store.clear_all_data(table_name)
        return SuccessResponse(
            message=f"All data for table '{table_name}' cleared successfully."
        )
    except Exception as e:
        response = {"message": "Internal Server Error", "detail": str(e)}
        raise HTTPException(status_code=500, detail=response)
