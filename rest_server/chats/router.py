from fastapi import APIRouter

router = APIRouter(prefix="/chats", tags=["Chats"])

from .create import *
from .delete import *
from .read import *
