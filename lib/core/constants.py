from enum import Enum


class ProfileTypeEnum(Enum):
    PATIENT = "patient"
    CARE_PROVIDER = "care_provider"
    ADMIN = "admin"


class CareProviderStatus(Enum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"


class EmitMessageKeyEnum(Enum):
    CHAT_LIST_UPDATED = "chat_list_updated"
    USER_STATUS_UPDATED = "user_status_updated"
    NEW_MESSAGE_RECEIVED = "new_message_received"
    MESSAGE_UPDATED = "message_updated"
    TYPING_INDICATOR = "typing_indicator"
    ALL_MESSAGES_MARKED_AS_READ = "all_messages_marked_as_read"
    MESSAGE_MARKED_AS_READ = "message_marked_as_read"


class FCMProjectEnum(Enum):
    PATIENT_APP = "aihealth-patient-app"
    CARE_PROVIDER_APP = "aihealth-care-provider-app"

    def get_fcm_api_url(self) -> str:
        return f"https://fcm.googleapis.com/v1/projects/{self.value}/messages:send"


AI_RESPONSE_SAFETY_DISCLAIMER = """
**Important Safety Guidelines:**
1. You are not a medical professional and must never claim to diagnose, treat, or cure any medical condition.
2. Do not suggest or recommend changes to medications, insulin doses, supplements, or treatment plans.
3. Avoid advising extreme or restrictive diets. Focus on balanced, evidence-based lifestyle guidance.
4. Always remind users to consult their doctor or qualified healthcare provider for individualized advice.
5. Use cautious language such as: "Based on general guidelines..." or "Some people find success with..."
6. If a question requires clinical judgment, respond with: "Please consult your doctor for personalized medical advice."
7. When uncertain or data is insufficient, clearly say so and encourage the user to seek professional input.
"""
