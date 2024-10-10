from typing import Any, List

from decouple import config
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_community.chat_models import ChatOpenAI
from pymongo import MongoClient

from lib.core.types import (ConversationMessageTypeLiteral,
                            ConversationRoleLiteral, ConversationTypeLiteral,
                            OpenAIModelLiteral)
from lib.schemas.conversation_message import \
    ConversationMessage as ConversationMessageSchema

MONGO_URL = config("MONGO_URL", default="mongodb://localhost:27017")
MONGO_DB_NAME = config("MONGO_DB_NAME", default="aihealth")


class LangChainService:
    def __init__(
        self,
        conversation_type: ConversationTypeLiteral,
        model: OpenAIModelLiteral = "gpt-4o",
    ):

        self.current_model = model
        self.mongo_client = MongoClient(str(MONGO_URL))
        self.db = self.mongo_client[str(MONGO_DB_NAME)]
        self.messages_collection = self.db["conversation_messages"]

        # Initialize ChatOpenAI with the specified model
        self.chat_model = ChatOpenAI(
            model=self.current_model,
            temperature=0.5,
            api_key=str(config("OPENAI_API_KEY")),
        )
        self.system_message = self._get_initial_system_message(
            conversation_type
        )

    def _get_initial_system_message(
        self, conversation_type: str
    ) -> SystemMessage:
        """Fetch the initial system message based on conversation type."""
        if conversation_type == "meal_analysis":
            return SystemMessage(
                content="You are a meal expert. Provide detailed analysis."
            )
        elif conversation_type == "prescription_analysis":
            return SystemMessage(
                content="You are a medical expert. Provide analysis of the prescription."
            )
        elif conversation_type == "report_analysis":
            return SystemMessage(
                content="You are a health report analyst. Provide insights on the report."
            )
        return SystemMessage(content="You are a knowledgeable assistant.")

    def add_message_to_conversation(
        self,
        conversation_id: str,
        role: ConversationRoleLiteral,
        content: str,
        message_type: ConversationMessageTypeLiteral = "text",
        exclude_from_frontend: bool = False,
    ):
        """Add a message to the conversation."""
        message_data = ConversationMessageSchema(
            conversation_id=conversation_id,
            role=role,
            content=content,
            message_type=message_type,
            exclude_from_frontend=exclude_from_frontend,
        ).model_dump()

        self.messages_collection.insert_one(message_data)

        # After adding a message, check if summarization is needed
        self.summarize_conversation_if_large(conversation_id)

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

    def generate_response(self, conversation_id: str, human_input: str) -> str:
        """Generate a response for the conversation."""
        # Add the user's input to the conversation first
        self.add_message_to_conversation(conversation_id, "human", human_input)

        # Fetch all messages in the conversation to provide context
        messages = self.fetch_conversation_messages(conversation_id)

        # Generate a response using the chat model
        ai_response = self.chat_model(messages)
        print("==> ai_response: ", ai_response)

        # Add AI response to the conversation
        self.add_message_to_conversation(
            conversation_id, "ai", ai_response.content
        )

        return ai_response.content

    def summarize_conversation_if_large(
        self, conversation_id: str, max_tokens: int = 1000
    ):
        """Summarize the conversation if it's too large."""
        messages = self.fetch_conversation_messages(conversation_id)
        total_tokens = sum([len(msg.content.split()) for msg in messages])

        if total_tokens > max_tokens:
            summary_prompt = "Summarize the following conversation: \n\n"
            for message in messages:
                summary_prompt += f"{message.role}: {message.content}\n"
            summary = self.chat_model([SystemMessage(content=summary_prompt)])

            # Add summary as a system message
            self.add_message_to_conversation(
                conversation_id, "system", summary.content
            )
