"""
LangGraph workflow setup for the health query agent.
"""

import asyncio
import logging
from time import perf_counter
from typing import TYPE_CHECKING, Optional

import instructor
from decouple import config
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from openai import OpenAI

from lib.core.cache_store import CacheStore
from lib.core.constants import ProfileTypeEnum
from lib.core.mongo_store import MongoStore
from lib.core.qdrant_store import QdrantStore
from .checkpointer import RedisCheckpointSaver
from .serialization import to_checkpoint_safe
from .v2 import (
    AgentState,
    ConversationContext,
    PlaybookLoader,
    PromptBuilder,
    QueryIntent,
    ResponseWriterSupport,
    StructuredAnalyzer,
    ToolExecutor,
    V2Planner,
)
from .v2.patient_summary_bridge import (
    resolve_summary_window,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from langgraph.graph import CompiledGraph

OPENAI_API_KEY: str = config("OPENAI_API_KEY", default="")
FINAL_LLM_TIMEOUT_SEC: float = float(
    config("HEALTH_QUERY_FINAL_LLM_TIMEOUT_SEC", default=12)
)


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


def get_user_role(state: AgentState) -> ProfileTypeEnum:
    try:
        return ProfileTypeEnum(state.get("user_role"))
    except Exception:
        return ProfileTypeEnum.PATIENT


def _runtime_context_messages(state: AgentState) -> list[dict]:
    messages: list[dict] = []

    raw_context = state.get("conversation_context") or {}
    if raw_context:
        try:
            context = ConversationContext(**raw_context)
            if context.system_note():
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Use this runtime conversation context when resolving follow-ups, "
                            "goals, preferences, and inherited time scopes:\n"
                            f"{context.system_note()}"
                        ),
                    }
                )
        except Exception:
            pass

    patient_memory_facts = state.get("patient_memory_facts") or []
    if patient_memory_facts:
        compact = []
        for fact in patient_memory_facts[:8]:
            key = fact.get("key")
            value = fact.get("value")
            if key:
                compact.append(f"- {key}: {value}")
        if compact:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Use these durable patient memory facts only when relevant to the "
                        "current question:\n" + "\n".join(compact)
                    ),
                }
            )

    return messages


def _llm_messages(state: AgentState, max_messages: int = 10) -> list[dict]:
    messages = state.get("messages") or []
    if max_messages <= 0:
        return []
    return messages[-max_messages:]


def _build_retrieval_metrics(
    payload_items: list[dict],
    executed_tools: list[str],
    retrieval_plan,
    warnings: Optional[list[str]] = None,
    degraded_tools: Optional[list[str]] = None,
) -> dict:
    by_data_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for item in payload_items:
        data_type = item.get("data_type", "unknown")
        source = item.get("source", "unknown")
        by_data_type[data_type] = by_data_type.get(data_type, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1

    return {
        "executed_tools": executed_tools,
        "payload_count": len(payload_items),
        "by_data_type": by_data_type,
        "by_source": by_source,
        "used_qdrant": retrieval_plan.use_qdrant,
        "used_patient_summary": retrieval_plan.use_patient_summary,
        "tool_chain": retrieval_plan.tool_chain,
        "result_limit": retrieval_plan.result_limit,
        "warnings": warnings or [],
        "degraded_tools": degraded_tools or [],
        "degraded": bool(warnings or degraded_tools),
    }


def _build_no_data_response(intent_plan, retrieval_plan) -> str:
    from .v2.response_formatter import ResponseFormatter

    return ResponseFormatter().render_no_data(
        intent_plan=intent_plan,
        retrieval_plan=retrieval_plan,
    )


def _can_execute_from_summary_only(state: AgentState) -> bool:
    raw_context = state.get("conversation_context") or {}
    if not raw_context:
        return False
    try:
        conversation_context = ConversationContext(**raw_context)
    except Exception:
        return False

    has_summary_domain = any(
        domain.value in {"sleep", "vitals", "patient_summary"}
        for domain in conversation_context.inherited_domains
    )
    if not has_summary_domain:
        return False

    return bool(resolve_summary_window(state["intent"], conversation_context))


def analyze_intent(state: AgentState) -> dict:
    role = get_user_role(state)
    role_str = "care-provider" if role == ProfileTypeEnum.CARE_PROVIDER else "patient"
    intent_prompt = PromptBuilder().get_intent_extraction_prompt(role=role_str)

    response = instructor_client.client.chat.completions.create(
        model="gpt-4.1-mini",
        response_model=QueryIntent,
        messages=[
            {"role": "system", "content": intent_prompt},
            *_runtime_context_messages(state),
            *_llm_messages(state, max_messages=8),
        ],
        temperature=0.0,
    )
    return {"intent": response}


async def execute_query(
    state: AgentState,
    qdrant_store: QdrantStore,
    mongo_store: Optional[MongoStore] = None,
) -> dict:
    stage_started = perf_counter()
    stage_timings_ms: dict[str, int] = {}
    intent = state["intent"]
    source_messages = state["messages"].copy() if state.get("messages") else []

    raw_context = state.get("conversation_context") or {}
    if raw_context:
        conversation_context = ConversationContext(**raw_context)
    else:
        last_message = state["messages"][-1]["content"] if state.get("messages") else ""
        conversation_context = ConversationContext(
            message_kind="fresh_query",
            user_message=last_message,
            normalized_message=last_message,
        )

    planner = V2Planner(playbook_loader=PlaybookLoader())
    intent_plan = planner.build_intent_plan(intent, conversation_context)
    retrieval_plan = planner.build_retrieval_plan(intent_plan)

    can_execute_summary_only = _can_execute_from_summary_only(state)
    if not intent.is_ready and not can_execute_summary_only:
        return {
            "final_response": "Query is not ready for execution.",
            "source_messages": source_messages,
            "intent_plan": to_checkpoint_safe(intent_plan),
            "retrieval_plan": to_checkpoint_safe(retrieval_plan),
        }

    user_message = state["messages"][-1]["content"] if state["messages"] else ""
    patient_ids = state.get("patient_ids")

    tool_result = await ToolExecutor().execute(
        user_message=user_message,
        patient_ids=patient_ids,
        intent=intent,
        intent_plan=intent_plan,
        retrieval_plan=retrieval_plan,
        conversation_context=conversation_context,
        qdrant_store=qdrant_store,
        mongo_store=mongo_store,
    )
    stage_timings_ms["tool_execution"] = int((perf_counter() - stage_started) * 1000)
    analysis_started = perf_counter()
    payload_items = tool_result.payload_items
    search_confidence = tool_result.search_confidence
    retrieval_metrics = _build_retrieval_metrics(
        payload_items=payload_items,
        executed_tools=tool_result.executed_tools,
        retrieval_plan=retrieval_plan,
        warnings=getattr(tool_result, "warnings", []),
        degraded_tools=getattr(tool_result, "degraded_tools", []),
    )
    logger.info(
        "Health query retrieval completed tools=%s payload_count=%s sources=%s data_types=%s",
        retrieval_metrics["executed_tools"],
        retrieval_metrics["payload_count"],
        retrieval_metrics["by_source"],
        retrieval_metrics["by_data_type"],
    )

    thread_state = state.get("thread_state") or {}
    analysis_snapshot = StructuredAnalyzer.build_snapshot(
        raw_points=payload_items,
        intent_plan=intent_plan,
        retrieval_plan=retrieval_plan,
        patient_id=patient_ids[0] if patient_ids and len(patient_ids) == 1 else None,
        thread_id=thread_state.get("thread_id"),
    )
    stage_timings_ms["analysis"] = int((perf_counter() - analysis_started) * 1000)

    if not payload_items:
        retrieval_metrics["stage_timings_ms"] = stage_timings_ms
        return {
            "final_response": _build_no_data_response(intent_plan, retrieval_plan),
            "search_confidence": search_confidence,
            "source_messages": source_messages,
            "intent_plan": to_checkpoint_safe(intent_plan),
            "retrieval_plan": to_checkpoint_safe(retrieval_plan),
            "analysis_snapshot": to_checkpoint_safe(analysis_snapshot),
            "executed_tools": tool_result.executed_tools,
            "retrieval_metrics": retrieval_metrics,
        }

    response_draft = ResponseWriterSupport().build_draft(
        intent_plan=intent_plan,
        retrieval_plan=retrieval_plan,
        analysis=analysis_snapshot,
    )

    role = get_user_role(state)
    role_str = "care-provider" if role == ProfileTypeEnum.CARE_PROVIDER else "patient"
    response_prompt_content = PromptBuilder().get_response_prompt(user_role=role_str)

    messages = [
        {"role": "system", "content": response_prompt_content},
        {"role": "system", "content": response_draft.system_addendum},
        *_runtime_context_messages(state),
        *_llm_messages(state, max_messages=10),
        {
            "role": "assistant",
            "content": f"[Structured analysis: {response_draft.analysis_payload}]",
        },
    ]

    llm_started = perf_counter()
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(
                openai_client.client.chat.completions.create,
                model="gpt-5.1",
                messages=messages,
            ),
            timeout=FINAL_LLM_TIMEOUT_SEC,
        )
        conversational_response = response.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("Health query final LLM degraded to deterministic fallback: %s", exc)
        retrieval_metrics["warnings"] = [
            *(retrieval_metrics.get("warnings") or []),
            "Final language generation degraded to deterministic fallback output.",
        ]
        retrieval_metrics["degraded"] = True
        conversational_response = ResponseWriterSupport().response_formatter.render_fallback_text(
            intent_plan=intent_plan,
            analysis=analysis_snapshot,
            warnings=retrieval_metrics["warnings"],
        )
    stage_timings_ms["final_llm"] = int((perf_counter() - llm_started) * 1000)
    retrieval_metrics["stage_timings_ms"] = stage_timings_ms

    return {
        "final_response": conversational_response,
        "search_confidence": search_confidence,
        "source_messages": source_messages,
        "intent_plan": to_checkpoint_safe(intent_plan),
        "retrieval_plan": to_checkpoint_safe(retrieval_plan),
        "analysis_snapshot": to_checkpoint_safe(analysis_snapshot),
        "executed_tools": tool_result.executed_tools,
        "retrieval_metrics": retrieval_metrics,
    }


def should_continue(state: AgentState) -> str:
    return "execute" if state["intent"].is_ready or _can_execute_from_summary_only(state) else END


def build_workflow(
    qdrant_store: QdrantStore,
    mongo_store: Optional[MongoStore] = None,
    cache_store: Optional[CacheStore] = None,
    use_cache_store: bool = True,
) -> "CompiledGraph":
    workflow = StateGraph(AgentState)

    async def execute_with_store(state: AgentState) -> dict:
        return await execute_query(state, qdrant_store, mongo_store=mongo_store)

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
