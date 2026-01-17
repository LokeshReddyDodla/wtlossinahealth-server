"""
LangGraph workflow setup for the health query agent.
"""

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import instructor
from decouple import config
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from openai import OpenAI

from lib.core.cache_store import CacheStore
from lib.core.constants import ProfileTypeEnum
from lib.core.qdrant_store import QdrantStore
from .prompts import (
    get_system_prompt_for_patient,
    get_system_prompt_for_care_provider,
    get_response_prompt,
)
from .schemas import AgentState, QueryIntent
from .checkpointer import RedisCheckpointSaver
from .qdrant_search import search_qdrant

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from langgraph.graph import CompiledGraph

# Configuration
OPENAI_API_KEY: str = config("OPENAI_API_KEY", default="")
OPENAI_MODEL: str = config("OPENAI_MODEL", default="gpt-4o-mini")
MAX_RESPONSE_TOKENS: int = int(config("MAX_RESPONSE_TOKENS", default="150"))
RESPONSE_TEMPERATURE: float = float(config("RESPONSE_TEMPERATURE", default="0.7"))


# ---------------------- API Clients ---------------------- #
class OpenAIWrapper:
    def __init__(self, use_instructor: bool = False):
        self._client = (
            instructor.from_openai(OpenAI(api_key=OPENAI_API_KEY))
            if use_instructor
            else OpenAI(api_key=OPENAI_API_KEY)
        )

    @property
    def client(self):
        return self._client


instructor_client = OpenAIWrapper(use_instructor=True)
openai_client = OpenAIWrapper()

# ---------------------- Role & Prompt Helpers ---------------------- #


def get_user_role(state: AgentState) -> ProfileTypeEnum:
    """Safely extract user role from state."""
    try:
        return ProfileTypeEnum(state.get("user_role"))
    except Exception:
        return ProfileTypeEnum.PATIENT


def get_system_prompt(state: AgentState, current_time: str) -> str:
    """Resolve system prompt based on user role."""
    role = get_user_role(state)

    if role == ProfileTypeEnum.CARE_PROVIDER:
        return get_system_prompt_for_care_provider(current_time)

    return get_system_prompt_for_patient(current_time)


# ---------------------- Workflow Nodes ---------------------- #


def analyze_intent(state: AgentState) -> dict:
    """Analyze user intent from the conversation state using Instructor embeddings."""
    current_time = datetime.now().isoformat()
    system_prompt = get_system_prompt(state, current_time)

    response = instructor_client.client.chat.completions.create(
        model=OPENAI_MODEL,
        response_model=QueryIntent,
        messages=[
            {"role": "system", "content": system_prompt},
            *state["messages"],
        ],
    )
    return {"intent": response}


async def execute_query(state: AgentState, qdrant_store: QdrantStore) -> dict:
    """Execute the user query and return conversational response."""
    intent = state["intent"]
    if not intent.is_ready:
        return {
            "final_response": "Query is not ready for execution.",
        }

    current_time = datetime.now().isoformat()
    user_message = state["messages"][-1]["content"] if state["messages"] else ""
    patient_ids = state.get("patient_ids")

    # Perform Qdrant search
    results, search_confidence = await search_qdrant(
        query=user_message,
        intent=intent,
        qdrant_store=qdrant_store,
        patient_ids=patient_ids,
    )

    logger.info(f"Length of results: {len(results)}")

    # Extract payload data from Qdrant results
    # Limit to top 50 results to prevent token overflow
    payload_items = []
    for point in results[:50]:
        if hasattr(point, 'payload') and point.payload:
            payload_items.append({**point.payload, "source": "qdrant"})

    # Build structured context from extracted payloads
    # Convert to JSON string for LLM context, handling datetime serialization
    retrieved_data_context = json.dumps(payload_items, default=str) if payload_items else "[]"

    # Get role-aware response prompt
    user_role = state.get("user_role", "patient")
    response_prompt_content = get_response_prompt(current_time, user_role=user_role)

    # Build message structure: [system prompt, conversation history, retrieved data context, LLM generates response]
    messages = [
        {"role": "system", "content": response_prompt_content},
        *state["messages"],
    ]
    
    # Add retrieved data context if we have payloads
    if payload_items:
        messages.append({
            "role": "assistant",
            "content": f"[Retrieved data from query: {retrieved_data_context}]",
        })

    response = openai_client.client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=MAX_RESPONSE_TOKENS,
        temperature=RESPONSE_TEMPERATURE,
    )

    conversational_response = response.choices[0].message.content.strip()

    return {
        "final_response": conversational_response,
        "search_confidence": search_confidence,
    }


def should_continue(state: AgentState) -> str:
    """Determine next workflow step based on intent readiness."""
    return "execute" if state["intent"].is_ready else END


# ---------------------- Workflow Builder ---------------------- #


def build_workflow(
    qdrant_store: QdrantStore,
    cache_store: Optional[CacheStore] = None,
    use_cache_store: bool = True,
) -> "CompiledGraph":
    """Build and compile the LangGraph workflow for health queries."""
    workflow = StateGraph(AgentState)

    async def execute_with_store(state: AgentState) -> dict:
        return await execute_query(state, qdrant_store)

    workflow.add_node("analyze", analyze_intent)
    workflow.add_node("execute", execute_with_store)

    workflow.add_edge(START, "analyze")
    workflow.add_conditional_edges(
        "analyze", should_continue, {"execute": "execute", END: END}
    )
    workflow.add_edge("execute", END)

    if use_cache_store:
        try:
            checkpointer = RedisCheckpointSaver(cache_store=cache_store)
            return workflow.compile(checkpointer=checkpointer)
        except Exception as e:
            logger.warning(
                f"Failed to initialize Redis checkpointer, falling back to MemorySaver: {e}"
            )

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
