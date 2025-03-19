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
    ALL_MESSAGES_MARKED_AS_READ = "all_messages_marked_as_read"
    MESSAGE_MARKED_AS_READ = "message_marked_as_read"


class FCMProject(Enum):
    PATIENT_APP = "aihealth-patient-app"
    CARE_PROVIDER_APP = "aihealth-care-provider-app"

    def get_fcm_api_url(self) -> str:
        return f"https://fcm.googleapis.com/v1/projects/{self.value}/messages:send"


AI_RESPONSE_SAFETY_DISCLAIMER = """
**Important Safety Guidelines:**
1. Never claim to diagnose, treat, or cure any medical condition.
2. Avoid suggesting changes to insulin doses, medications, or extreme diets.
3. Always recommend consulting a doctor or healthcare provider for personalized advice.
4. Use phrases like "Based on general guidelines..." or "Some people find success with..." to avoid absolute claims.
5. If unsure, respond with: "Please consult your doctor for personalized advice."
"""
