from fastapi import APIRouter

router = APIRouter(
    prefix="/care-provider/conversation/{conversation_id}",
    tags=["AI Conversations - Care Provider"],
)


from .create import *
from .read import *
