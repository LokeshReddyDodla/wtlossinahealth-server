import httpx
from fastapi import HTTPException


async def check_user_api_health():
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/health") # TODO: Update this
            if response.status_code == 200:
                return "available"
            else:
                raise HTTPException(status_code=503, detail="User API unavailable")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="User API unavailable")
            raise HTTPException(status_code=503, detail="User API unavailable")
