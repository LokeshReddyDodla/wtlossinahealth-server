from fastapi import APIRouter

router = APIRouter(prefix="/chats", tags=["Chats"])

from .create import *
from .read import *
