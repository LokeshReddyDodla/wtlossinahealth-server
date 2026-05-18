"""Inline sender profile attached to every chat message.

Eliminates the race where the message broadcast arrives before the chat
roster update, leaving the client unable to render the sender name.
Always non-null in API responses — we synthesize an "Unknown User"
profile rather than omit the field, so clients never need a fallback.
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

SenderProfileRoleLiteral = Literal[
    "patient",
    "care_provider",
    "admin",
    "support_staff",
]


class SenderProfileSchema(BaseModel):
    """Compact profile attached inline to every message and to every
    participant in chat responses.

    ``role`` is the high-level enum that drives client-side bucketing
    (avatar fallback, color, tab placement). ``subrole`` carries the
    care-provider specialty as a free string passed through from
    ``CareProvider.role`` ("Doctor", "Nurse", "Dietitian", ...); it is
    None for non-CPs and for CPs whose top-level role is already
    ``support_staff`` (the enum already encodes that case).
    """

    first_name: str
    last_name: str
    profile_picture: Optional[str] = None
    role: SenderProfileRoleLiteral
    subrole: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


UNKNOWN_SENDER_PROFILE = SenderProfileSchema(
    first_name="Unknown",
    last_name="User",
    profile_picture=None,
    role="patient",  # safe default; clients render generic avatar
    subrole=None,
)
