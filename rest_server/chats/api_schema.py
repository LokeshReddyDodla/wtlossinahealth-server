from datetime import datetime
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field, HttpUrl, constr

from lib.schemas.chat import ChatSchema
from rest_server.response_models import SuccessResponse

ChatResponse = SuccessResponse[ChatSchema]
