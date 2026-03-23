"""V2 foundations for the health query agent."""

__all__ = [
    "AgentState",
    "AnalysisSnapshot",
    "ConversationHistoryResponse",
    "ConversationMessage",
    "ConversationCompaction",
    "ConversationContext",
    "ConversationLexicon",
    "ConversationLexiconLoader",
    "ConversationMessageKind",
    "ConversationResolver",
    "DomainName",
    "HealthAgentMemoryRepository",
    "HealthDataType",
    "IntentPlan",
    "NumericFilter",
    "NumericRange",
    "PatientMemoryFact",
    "PlaybookLoader",
    "ResponseDraft",
    "ResponseMode",
    "ResponseWriterSupport",
    "PromptBuilder",
    "QueryIntent",
    "QueryResponse",
    "RetrievalPlan",
    "StructuredAnalyzer",
    "MongoReportFetcher",
    "ResponseFormatter",
    "FilterBuilder",
    "search_qdrant",
    "ToolExecutionResult",
    "ToolExecutor",
    "ThreadState",
    "SuggestedAction",
    "DateRange",
    "TimeRange",
    "V2Planner",
]


def __getattr__(name: str):
    if name in {
        "AgentState",
        "AnalysisSnapshot",
        "ConversationHistoryResponse",
        "ConversationMessage",
        "ConversationCompaction",
        "ConversationContext",
        "ConversationMessageKind",
        "DomainName",
        "HealthDataType",
        "IntentPlan",
        "NumericFilter",
        "NumericRange",
        "PatientMemoryFact",
        "QueryIntent",
        "QueryResponse",
        "ResponseDraft",
        "ResponseMode",
        "RetrievalPlan",
        "SuggestedAction",
        "DateRange",
        "ThreadState",
        "TimeRange",
    }:
        from .contracts import (
            AgentState,
            ConversationHistoryResponse,
            ConversationMessage,
            DateRange,
            HealthDataType,
            NumericFilter,
            NumericRange,
            QueryIntent,
            QueryResponse,
            SuggestedAction,
            TimeRange,
        )
        from .models import (
            AnalysisSnapshot,
            ConversationCompaction,
            ConversationContext,
            ConversationMessageKind,
            DomainName,
            IntentPlan,
            PatientMemoryFact,
            ResponseDraft,
            ResponseMode,
            RetrievalPlan,
            ThreadState,
        )

        return locals()[name]
    if name in {"ConversationLexicon", "ConversationLexiconLoader"}:
        from .conversation_lexicon import ConversationLexicon, ConversationLexiconLoader

        return locals()[name]
    if name == "PlaybookLoader":
        from .playbook_loader import PlaybookLoader

        return PlaybookLoader
    if name == "PromptBuilder":
        from .prompt_builder import PromptBuilder

        return PromptBuilder
    if name == "HealthAgentMemoryRepository":
        from .memory_repository import HealthAgentMemoryRepository

        return HealthAgentMemoryRepository
    if name == "ConversationResolver":
        from .conversation_resolver import ConversationResolver

        return ConversationResolver
    if name == "V2Planner":
        from .planner import V2Planner

        return V2Planner
    if name == "StructuredAnalyzer":
        from .analysis import StructuredAnalyzer

        return StructuredAnalyzer
    if name in {"ToolExecutionResult", "ToolExecutor"}:
        from .tool_executor import ToolExecutionResult, ToolExecutor

        return locals()[name]
    if name == "MongoReportFetcher":
        from .report_fetcher import MongoReportFetcher

        return MongoReportFetcher
    if name == "FilterBuilder":
        from .filter_builder import FilterBuilder

        return FilterBuilder
    if name == "search_qdrant":
        from .qdrant_search import search_qdrant

        return search_qdrant
    if name == "ResponseFormatter":
        from .response_formatter import ResponseFormatter

        return ResponseFormatter
    if name == "ResponseWriterSupport":
        from .response_writer import ResponseWriterSupport

        return ResponseWriterSupport
    raise AttributeError(name)
