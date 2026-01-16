"""
LangGraph workflow setup for the health query agent.
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import instructor
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from openai import OpenAI
import redis

from lib.core.qdrant_store import QdrantStore
from microservices.health_query_agent.config import settings
from .prompts import get_system_prompt, get_response_prompt, get_data_type_display_names
from .schemas import AgentState, QueryIntent
from .checkpointer import RedisCheckpointSaver
from .qdrant_search import search_qdrant

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from langgraph.graph import CompiledGraph


# ---------------------- API Clients ---------------------- #
class OpenAIWrapper:
    def __init__(self, use_instructor: bool = False):
        self._client = (
            instructor.from_openai(OpenAI(api_key=settings.OPENAI_API_KEY))
            if use_instructor
            else OpenAI(api_key=settings.OPENAI_API_KEY)
        )

    @property
    def client(self):
        return self._client


instructor_client = OpenAIWrapper(use_instructor=True)
openai_client = OpenAIWrapper()

# ---------------------- Workflow Helpers ---------------------- #


def analyze_intent(state: AgentState) -> dict:
    """Analyze user intent from the conversation state using Instructor embeddings."""
    current_time = datetime.now().isoformat()
    response = instructor_client.client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        response_model=QueryIntent,
        messages=[
            {"role": "system", "content": get_system_prompt(current_time)},
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
            "messages": state["messages"],
        }

    current_time = datetime.now().isoformat()
    user_message = state["messages"][-1]["content"] if state["messages"] else ""

    # Get search parameters from state
    patient_ids = state.get("patient_ids")

    # Perform Qdrant search
    results, search_confidence = await search_qdrant(
        query=user_message,
        intent=intent,
        qdrant_store=qdrant_store,
        patient_ids=patient_ids,
    )

    # Format date range
    date_str = "the specified time period"
    if intent.date_range and intent.date_range.start:
        start = intent.date_range.start.strftime("%B %d, %Y")
        end = (
            intent.date_range.end.strftime("%B %d, %Y")
            if intent.date_range.end
            else None
        )
        date_str = f"{start} to {end}" if end else start

    # Format data types
    data_type_names = get_data_type_display_names()
    data_type_display = ", ".join(
        [data_type_names.get(dt.value, dt.value) for dt in intent.data_types]
    )

    response = openai_client.client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {"role": "system", "content": get_response_prompt(current_time)},
            *state["messages"],
            {
                "role": "assistant",
                "content": f"[Query processed successfully. Retrieved {len(results)} results for {data_type_display} data for {date_str}.]",
            },
        ],
        max_tokens=settings.MAX_RESPONSE_TOKENS,
        temperature=settings.RESPONSE_TEMPERATURE,
    )

    conversational_response = response.choices[0].message.content.strip()

    return {
        "final_response": conversational_response,
        "messages": [],
        "search_confidence": search_confidence,
    }


def should_continue(state: AgentState) -> str:
    """Determine next workflow step based on intent readiness."""
    return "execute" if state["intent"].is_ready else END


# ---------------------- Workflow Builder ---------------------- #


def build_workflow(
    qdrant_store: QdrantStore,
    redis_client: Optional[redis.Redis] = None,
    use_redis: bool = True,
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

    if use_redis:
        try:
            checkpointer = RedisCheckpointSaver(redis_client=redis_client)
            return workflow.compile(checkpointer=checkpointer)
        except Exception as e:
            logger.warning(
                f"Failed to initialize Redis checkpointer, falling back to MemorySaver: {e}"
            )

    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)
