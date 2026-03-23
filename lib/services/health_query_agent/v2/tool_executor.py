from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

try:
    from decouple import config
except ImportError:  # pragma: no cover - test fallback
    def config(*_args, default=None, **_kwargs):
        return default

from .models import ConversationContext, IntentPlan, RetrievalPlan, ToolExecutionResult
from .patient_summary_bridge import build_patient_summary_payloads
from .report_fetcher import MongoReportFetcher

if TYPE_CHECKING:
    from lib.core.mongo_store import MongoStore
    from lib.core.qdrant_store import QdrantStore


REPORT_FETCH_TIMEOUT_SEC = float(
    config("HEALTH_QUERY_REPORT_FETCH_TIMEOUT_SEC", default=5)
)
QDRANT_TIMEOUT_SEC = float(config("HEALTH_QUERY_QDRANT_TIMEOUT_SEC", default=8))
PATIENT_SUMMARY_TIMEOUT_SEC = float(
    config("HEALTH_QUERY_PATIENT_SUMMARY_TIMEOUT_SEC", default=5)
)

class ToolExecutor:
    def __init__(self, report_fetcher: MongoReportFetcher | None = None):
        self.report_fetcher = report_fetcher or MongoReportFetcher()

    async def execute(
        self,
        *,
        user_message: str,
        patient_ids: Optional[list[str]],
        intent,
        intent_plan: IntentPlan,
        retrieval_plan: RetrievalPlan,
        conversation_context: ConversationContext,
        qdrant_store: "QdrantStore",
        mongo_store: Optional["MongoStore"] = None,
    ) -> ToolExecutionResult:
        result = ToolExecutionResult()

        for tool_name in retrieval_plan.tool_chain:
            if tool_name == "mongo_report_fetch":
                report_payloads = await self._run_required_tool(
                    tool_name=tool_name,
                    timeout_seconds=REPORT_FETCH_TIMEOUT_SEC,
                    coro=self.report_fetcher.fetch(
                        mongo_store=mongo_store,
                        patient_id=patient_ids[0] if patient_ids and len(patient_ids) == 1 else None,
                        intent=intent,
                        intent_plan=intent_plan,
                        conversation_context=conversation_context,
                    ),
                )
                result.payload_items.extend(report_payloads)
                result.executed_tools.append(tool_name)
                continue

            if tool_name == "qdrant_search" and retrieval_plan.use_qdrant:
                qdrant_outcome = await self._run_optional_tool(
                    tool_name=tool_name,
                    timeout_seconds=QDRANT_TIMEOUT_SEC,
                    coro=self._run_qdrant_search(
                        user_message=user_message,
                        intent=intent,
                        qdrant_store=qdrant_store,
                        patient_ids=patient_ids,
                        retrieval_plan=retrieval_plan,
                    ),
                )
                if qdrant_outcome is None:
                    result.degraded_tools.append(tool_name)
                    result.warnings.append(
                        "Semantic retrieval was unavailable, so the answer used only deterministic data."
                    )
                    continue
                points, search_confidence = qdrant_outcome
                for point in points:
                    if hasattr(point, "payload") and point.payload:
                        result.payload_items.append({**point.payload, "source": "qdrant"})
                result.search_confidence = search_confidence
                result.executed_tools.append(tool_name)
                continue

            if tool_name == "patient_summary_fetch":
                summary_payloads = await self._run_optional_tool(
                    tool_name=tool_name,
                    timeout_seconds=PATIENT_SUMMARY_TIMEOUT_SEC,
                    coro=build_patient_summary_payloads(
                        mongo_store=mongo_store,
                        patient_id=patient_ids[0]
                        if patient_ids and len(patient_ids) == 1
                        else None,
                        intent=intent,
                        intent_plan=intent_plan,
                        retrieval_plan=retrieval_plan,
                        conversation_context=conversation_context,
                    ),
                )
                if summary_payloads is None:
                    result.degraded_tools.append(tool_name)
                    result.warnings.append(
                        "Patient summary enrichment was unavailable for this request."
                    )
                    continue
                result.payload_items.extend(summary_payloads)
                result.executed_tools.append(tool_name)

        return result

    @staticmethod
    async def _run_required_tool(*, tool_name: str, timeout_seconds: float, coro):
        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"{tool_name} timed out after {timeout_seconds}s") from exc

    @staticmethod
    async def _run_optional_tool(*, tool_name: str, timeout_seconds: float, coro):
        try:
            return await asyncio.wait_for(coro, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    @staticmethod
    async def _run_qdrant_search(
        *,
        user_message: str,
        intent,
        qdrant_store: "QdrantStore",
        patient_ids: Optional[list[str]],
        retrieval_plan: RetrievalPlan,
    ):
        from .qdrant_search import search_qdrant

        return await search_qdrant(
            query=user_message,
            intent=intent,
            qdrant_store=qdrant_store,
            patient_ids=patient_ids,
            limit=retrieval_plan.result_limit,
        )
