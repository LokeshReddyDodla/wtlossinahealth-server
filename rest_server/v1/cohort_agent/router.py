from fastapi import APIRouter

router = APIRouter(prefix="/cohort-agent", tags=["V1 - Cohort Agent"])

from .query import *  # noqa: E402,F401,F403
