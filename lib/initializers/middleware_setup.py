from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.middlewares import create_context


ALLOWED_ORIGINS = [
    "https://api.aihealth.clinic",
    "http://localhost:3000",
    "https://aihealth.clinic",
    "https://www.aihealth.clinic",
    "http://localhost:4321",
]

def setup_middlewares(app):
    origins = ALLOWED_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=create_context)
