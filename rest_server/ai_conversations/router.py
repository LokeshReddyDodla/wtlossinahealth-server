from fastapi import APIRouter

router = APIRouter(prefix="/ai-conversation", tags=["Ai Conversation"])

from .create import *
from .read import *
