from datetime import datetime
from typing import List, Literal, Optional, Union
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, constr

from lib.core.types import (ConversationMessageTypeLiteral,
                            ConversationRoleLiteral)


class ConversationMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    role: ConversationRoleLiteral
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    message_type: ConversationMessageTypeLiteral = "text"
    exclude_from_frontend: bool = False
