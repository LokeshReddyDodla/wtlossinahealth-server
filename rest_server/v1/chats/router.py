from fastapi import APIRouter

router = APIRouter(prefix="/chats", tags=["Chats (v1)"])

from .read import *  # noqa: F401,E402,F403
