from typing import Any, List
from uuid import UUID

from decouple import config
from fastapi import HTTPException
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import SecretStr
from pymongo import MongoClient

from lib.core.types import (AiConversationMessageTypeLiteral,
                            AiConversationRoleLiteral,
                            AiConversationTypeLiteral, OpenAIModelLiteral)
from lib.schemas.ai_conversation_message import \
    AiConversationMessage as AiConversationMessageSchema
from lib.utils.patient_token_usage_logger import PatientTokenUsageLogger

MONGO_URL = config("MONGO_URL", default="mongodb://localhost:27017")
MONGO_DB_NAME = config("MONGO_DB_NAME", default="aihealth")


class AiConversationService:
    def __init__(
        self,
        conversation_type: AiConversationTypeLiteral,
        model: OpenAIModelLiteral = "gpt-4o",
    ):

        self.current_model = model
        self.mongo_client = MongoClient(str(MONGO_URL))
        self.db = self.mongo_client[str(MONGO_DB_NAME)]
        self.messages_collection = self.db["ai_conversation_messages"]

        # Initialize ChatOpenAI with the specified model
        self.chat_model = ChatOpenAI(
            model=self.current_model,
            temperature=0.5,
            api_key=SecretStr(str(config("OPENAI_API_KEY"))),
        )
        self.system_message = self._get_initial_system_message(
            conversation_type
        )

    def _get_initial_system_message(
        self, conversation_type: str
    ) -> SystemMessage:
        """Returns the initial system message based on conversation type."""
        system_messages = {
            "meal_analysis": "You are an AI strictly focused on meal analysis. Respond only with information related to meals, nutrition, and dietary insights in markdown format. Avoid any response that includes your origin, development, or unrelated topics.",
            "prescription_analysis": "You are an AI strictly focused on prescription analysis. Respond only with information related to prescriptions, medical details, and relevant insights in markdown format. Avoid any response that includes your origin, development, or unrelated topics.",
            "report_analysis": "You are an AI strictly focused on report analysis. Provide insights only about health reports and their content in markdown format. Avoid any response that includes your origin, development, or unrelated topics.",
        }
        return SystemMessage(
            content=system_messages.get(
                conversation_type,
                "You are a knowledgeable assistant. Respond only in the context of the ongoing conversation and provide all responses in markdown format. Avoid mentioning anything beyond the specific task.",
            )
        )

    def add_message_to_conversation(
        self,
        conversation_id: str,
        role: AiConversationRoleLiteral,
        content: str,
        message_type: AiConversationMessageTypeLiteral = "text",
        exclude_from_frontend: bool = False,
    ):
        """Add a message to the conversation."""
        message_data = AiConversationMessageSchema(
            conversation_id=conversation_id,
            role=role,
            content=content,
            message_type=message_type,
            exclude_from_frontend=exclude_from_frontend,
        ).model_dump()

        self.messages_collection.insert_one(message_data)

    def add_messages_to_conversation(
        self,
        messages: List[AiConversationMessageSchema],
    ):
        """Batch inserts multiple messages into a conversation."""
        message_data = [message.model_dump() for message in messages]
        self.messages_collection.insert_many(message_data)

    def fetch_conversation_messages(self, conversation_id: str) -> List[Any]:
        """Fetch all messages for a given conversation."""
        messages_cursor = self.messages_collection.find(
            {"conversation_id": conversation_id}
        ).sort("timestamp", 1)

        messages = []
        for message in messages_cursor:
            if message["role"] == "system":
                messages.append(SystemMessage(content=message["content"]))
            elif message["role"] == "human":
                messages.append(HumanMessage(content=message["content"]))
            elif message["role"] == "ai":
                messages.append(AIMessage(content=message["content"]))

        return messages

    async def generate_response(
        self, patient_id: str, conversation_id: str, human_input: str
    ) -> str:
        self.add_message_to_conversation(conversation_id, "human", human_input)

        # Fetch all messages to provide context, inserting the system message at the start
        messages = self.fetch_conversation_messages(conversation_id)
        messages.insert(0, self.system_message)

        # Generate a response using the chat model
        ai_response: Any = self.chat_model.invoke(messages)
        self.add_message_to_conversation(
            conversation_id, "ai", ai_response.content, message_type="markdown"
        )

        # Log token usage
        tokens_used = ai_response.response_metadata.get("token_usage", {}).get(
            "total_tokens", 0
        )
        if tokens_used:
            await PatientTokenUsageLogger.log_usage(
                patient_id=UUID(patient_id),
                tokens_used=tokens_used,
                model_used=self.current_model,
                api_type="openai",
                api_endpoint="conversation_response",
            )

        return ai_response.content

    def delete_conversation_messages(self, conversation_id: str):
        """Deletes all messages for a given conversation."""
        try:
            delete_result = self.messages_collection.delete_many(
                {"conversation_id": conversation_id}
            )
            return delete_result
        except Exception as e:
            print(f"Failed to delete conversation messages: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Failed to delete conversation messages",
            )
