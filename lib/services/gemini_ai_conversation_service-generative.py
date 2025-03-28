# from pprint import pprint
# from typing import Any, Dict, List, Optional, Type
# from uuid import UUID

# import google.generativeai as genai
# from decouple import config
# from fastapi import status
# from langchain.schema import AIMessage, HumanMessage, SystemMessage
# from pydantic import SecretStr

# from lib.core.constants import ProfileTypeEnum
# from lib.core.types import (AiConversationMessageTypeLiteral,
#                             AiConversationRoleLiteral,
#                             AiConversationTypeLiteral, GeminiAIModelLiteral,
#                             OpenAIModelLiteral)
# from lib.dependencies.service_dependencies import (
#     get_ai_conversation_messages_collection, get_patient_profile_service,
#     get_token_usage_service)
# from lib.schemas.ai_conversation_schemas import \
#     AiConversationMessage as AiConversationMessageSchema
# from lib.schemas.ai_conversation_schemas import (AIResponse,
#                                                  AiResponseSuggestions)
# from lib.schemas.patient import CorePatientProfile
# from lib.services.patient_profile_service import PatientProfileService
# from lib.services.token_usage_service import TokenUsageService
# from lib.utils.http_exceptions import raise_http_exception
# from lib.utils.retry_utils import retry_request

# from .system_messages.base_system_message import BaseSystemMessage
# from .system_messages.health_tip_system_message import HealthTipSystemMessage
# from .system_messages.meal_system_message import MealSystemMessage
# from .system_messages.prescription_system_message import \
#     PrescriptionSystemMessage
# from .system_messages.report_system_message import ReportSystemMessage
# from .system_messages.sleep_system_message import SleepSystemMessage
# from .system_messages.smbg_system_message import SMBGSystemMessage


# class GeminiAIConversationService:
#     _SYSTEM_MESSAGE_MAP: Dict[
#         AiConversationTypeLiteral, Type[BaseSystemMessage]
#     ] = {
#         "meal": MealSystemMessage,
#         "smbg": SMBGSystemMessage,
#         "sleep": SleepSystemMessage,
#         "prescription": PrescriptionSystemMessage,
#         "report": ReportSystemMessage,
#         "health-tip": HealthTipSystemMessage,
#     }

#     _ROLE_MAPPING = {
#         "human": "user",
#         "ai": "model",
#         "system": "system",
#     }

#     def __init__(
#         self,
#         conversation_type: AiConversationTypeLiteral = "other",
#         model: GeminiAIModelLiteral = "gemini-2.0-flash",
#     ):

#         self.token_usage_service = get_token_usage_service()
#         self.patient_profile_service = get_patient_profile_service()
#         self.ai_messages_collection: Any = (
#             get_ai_conversation_messages_collection()
#         )
#         self.current_model: GeminiAIModelLiteral = model

#         # Initialize google.generativeai
#         genai.configure(api_key=str(config("GOOGLE_API_KEY")))
#         self.chat_model = genai.GenerativeModel(model_name=self.current_model)
#         self.system_message = self._get_initial_system_message(
#             conversation_type
#         )

#     def _get_initial_system_message(
#         self, conversation_type: AiConversationTypeLiteral
#     ) -> Dict:
#         return (
#             self._SYSTEM_MESSAGE_MAP.get(
#                 conversation_type, BaseSystemMessage
#             )()
#             .get_system_message()
#             .model_dump()
#         )

#     async def add_message_to_conversation(
#         self,
#         patient_id: str,
#         conversation_id: str,
#         conversation_type: AiConversationTypeLiteral,
#         role: AiConversationRoleLiteral,
#         content: str,
#         message_type: AiConversationMessageTypeLiteral = "text",
#         exclude_from_frontend: bool = False,
#         follow_up_questions: Optional[List[str]] = None,
#         metadata: Optional[Dict] = None,
#     ) -> Dict:
#         message_data = AiConversationMessageSchema(
#             patient_id=patient_id,
#             conversation_id=conversation_id,
#             conversation_type=conversation_type,
#             role=role,
#             content=content,
#             message_type=message_type,
#             exclude_from_frontend=exclude_from_frontend,
#             reply_suggestions=follow_up_questions,
#             metadata=metadata,
#         ).model_dump()

#         result = await self.ai_messages_collection.insert_one(message_data)
#         message_data["_id"] = str(result.inserted_id)
#         return message_data

#     async def add_multiple_messages_to_conversation(
#         self,
#         messages: List[AiConversationMessageSchema],
#     ) -> None:
#         """Batch inserts multiple messages into a conversation."""
#         message_data = [message.model_dump() for message in messages]
#         await self.ai_messages_collection.insert_many(message_data)

#     async def fetch_conversation_messages(
#         self,
#         conversation_id: str,
#         return_raw: bool = False,
#         for_frontend: bool = False,
#     ) -> List[Any]:
#         """Fetch all messages for a given conversation."""
#         filters: Any = {"conversation_id": conversation_id}

#         if for_frontend:
#             filters["exclude_from_frontend"] = False

#         pipeline = [
#             {"$match": filters},
#             {"$sort": {"timestamp": 1}},
#             {"$addFields": {"_id": {"$toString": "$_id"}}},
#         ]
#         messages_cursor = self.ai_messages_collection.aggregate(pipeline)
#         if return_raw:
#             return await messages_cursor.to_list(length=None)

#         return await self.ai_messages_collection.aggregate(pipeline).to_list(
#             length=None
#         )

#     async def fetch_user_entire_conversation_messages(
#         self,
#         patient_id: str,
#     ) -> List[Any]:
#         """Fetch all messages for a given conversation."""
#         filters: Any = {"patient_id": patient_id}
#         pipeline = [
#             {"$match": filters},
#             {"$sort": {"timestamp": 1}},
#             {"$addFields": {"_id": {"$toString": "$_id"}}},
#         ]

#         return await self.ai_messages_collection.aggregate(pipeline).to_list(
#             length=None
#         )

#     async def create_patient_context_message(self, patient_id: str) -> Dict:
#         patient = await self.patient_profile_service.fetch_patient_profile(
#             patient_id=patient_id, detailed=True, include_health_data=True
#         )
#         patient_profile_json = CorePatientProfile.from_orm(
#             patient
#         ).model_dump()
#         return {
#             "role": "human",
#             "content": f"My Profile:\n```json\n{patient_profile_json}\n```",
#         }

#     async def generate_response(
#         self,
#         patient_id: str,
#         conversation_id: str,
#         human_input: str,
#         conversation_type: AiConversationTypeLiteral,
#     ) -> Dict:
#         await self.add_message_to_conversation(
#             patient_id,
#             conversation_id,
#             conversation_type,
#             "human",
#             human_input,
#         )

#         messages = (
#             await self.fetch_user_entire_conversation_messages(patient_id)
#             if conversation_id == f"{patient_id}-custom"
#             else await self.fetch_conversation_messages(conversation_id)
#         )
#         # messages.insert(0, self.system_message)

#         patient_context_message = await self.create_patient_context_message(
#             patient_id
#         )
#         messages.insert(1, patient_context_message)

#         gemini_messages = [
#             {
#                 "role": self._ROLE_MAPPING[msg["role"]],
#                 "parts": [msg["content"]],
#             }
#             for msg in messages
#         ]
#         pprint(gemini_messages)

#         ai_response = self.chat_model.generate_content(gemini_messages)
#         pprint(ai_response)

#         citation_metadata = next(
#             (
#                 c.citation_metadata
#                 for c in ai_response.candidates
#                 if c.citation_metadata and c.citation_metadata.citations
#             ),
#             None,
#         )
#         pprint(citation_metadata)

#         ai_message_data = await self.add_message_to_conversation(
#             patient_id,
#             conversation_id,
#             conversation_type,
#             "ai",
#             ai_response.text,
#             message_type="markdown",
#             follow_up_questions=None,
#             metadata={
#                 "citation": citation_metadata,
#             },
#         )

#         usage_metadata = ai_response.usage_metadata

#         # Log token usage
#         if usage_metadata:
#             await self.token_usage_service.log_usage(
#                 user_id=patient_id,
#                 user_type=ProfileTypeEnum.PATIENT,
#                 input_tokens=usage_metadata.prompt_token_count,
#                 output_tokens=usage_metadata.candidates_token_count,
#                 cached_input_tokens=usage_metadata.cached_content_token_count,
#                 model_used=self.current_model,
#                 api_type="gemini",
#                 api_endpoint="/ai-conversation/respond",
#             )

#         return ai_message_data

#     async def delete_conversation_messages(
#         self,
#         conversation_id: str,
#     ):
#         """Deletes all messages for a given conversation."""
#         try:
#             delete_result = await self.ai_messages_collection.delete_many(
#                 {"conversation_id": conversation_id}
#             )
#             return delete_result

#         except ValueError as ve:
#             raise_http_exception(
#                 status_code=status.HTTP_400_BAD_REQUEST,
#                 message="Invalid input for deleting conversation messages.",
#                 detail=str(ve),
#             )
#         except Exception as e:
#             raise_http_exception(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 message="An unexpected error occurred while deleting conversation messages.",
#                 detail=str(e),
#             )
