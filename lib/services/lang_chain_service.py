from typing import Any

import openai
from decouple import config
from langchain.memory import MongoDBMemory
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from langchain_community.chat_models import ChatOpenAI
from pymongo import MongoClient

MONGO_URL = config("MONGO_URL", default="mongodb://localhost:27017")
MONGO_DB_NAME = config("MONGO_DB_NAME", default="aihealth")


class LangChainService:
    def __init__(self, model="gpt-4o"):

        self.current_model = model
        self.mongo_client = MongoClient(str(MONGO_URL))
        self.db = self.mongo_client[str(MONGO_DB_NAME)]
        self.collection = self.db["chat_contexts"]

        # Initialize ChatOpenAI with the specified model
        self.chat_model = ChatOpenAI()

    def create_conversation(self, user_message, context=[]):
        """
        Creates a conversation based on the user message and context.
        """
        messages: Any = [SystemMessage(content="You are a helpful assistant.")]

        # Add any previous context messages
        for message in context:
            if message["role"] == "user":
                messages.append(HumanMessage(content=message["content"]))
            elif message["role"] == "assistant":
                messages.append(AIMessage(content=message["content"]))

        # Add the new user message
        messages.append(HumanMessage(content=user_message))

        # Get the AI response
        response = self.chat_model(messages)

        # Store context into MongoDB for future conversations
        self.collection.insert_one(
            {
                "user_message": user_message,
                "assistant_message": response.content,
            }
        )

        return response.content
