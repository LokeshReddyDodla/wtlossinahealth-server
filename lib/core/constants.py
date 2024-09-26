from enum import Enum


class ProfileType(Enum):
    PATIENT = "patient"
    CARE_PROVIDER = "care_provider"
    ADMIN = "admin"


class EmitMessageKey(Enum):
    CHAT_LIST_UPDATED = "chat_list_updated"
    USER_STATUS_UPDATED = "user_status_updated"
    NEW_MESSAGE_RECEIVED = "new_message_received"
    MESSAGE_UPDATED = "message_updated"
    TYPING_INDICATOR = "typing_indicator"
    MESSAGE_READ = "message_read"
    ALL_MESSAGES_MARKED_AS_READ = "all_messages_marked_as_read"
    MESSAGE_MARKED_AS_READ = "message_marked_as_read"