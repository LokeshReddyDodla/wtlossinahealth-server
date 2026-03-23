from __future__ import annotations

from typing import Iterable, List

from .models import (
    ConversationContext,
    ConversationMessageKind,
    DomainName,
    IntentPlan,
    ResponseMode,
    RetrievalPlan,
)
from .contracts import HealthDataType
from .playbook_loader import PlaybookLoader


class V2Planner:
    MONGO_REPORT_BACKED_DOMAINS = {
        DomainName.MEAL,
        DomainName.CGM,
        DomainName.FITNESS,
        DomainName.SLEEP,
    }

    QDRANT_BACKED_DOMAINS = {
        DomainName.MEAL,
        DomainName.CGM,
        DomainName.SMBG,
        DomainName.FITNESS,
        DomainName.PROFILE,
        DomainName.DOCUMENTS,
    }

    DATA_TYPE_TO_DOMAIN = {
        HealthDataType.MEAL: DomainName.MEAL,
        HealthDataType.CGM_RANGE: DomainName.CGM,
        HealthDataType.CGM_SUMMARY: DomainName.CGM,
        HealthDataType.CGM_SEMANTIC_WINDOW: DomainName.CGM,
        HealthDataType.AGP: DomainName.CGM,
        HealthDataType.HYPER_STATS: DomainName.CGM,
        HealthDataType.HYPO_STATS: DomainName.CGM,
        HealthDataType.RAPID_SPIKE: DomainName.CGM,
        HealthDataType.RAPID_DROP: DomainName.CGM,
        HealthDataType.HYPER_EVENT: DomainName.CGM,
        HealthDataType.HYPO_EVENT: DomainName.CGM,
        HealthDataType.RAPID_SPIKE_EVENT: DomainName.CGM,
        HealthDataType.RAPID_DROP_EVENT: DomainName.CGM,
        HealthDataType.SMBG: DomainName.SMBG,
        HealthDataType.FITNESS_OVERVIEW: DomainName.FITNESS,
        HealthDataType.FITNESS_DIST: DomainName.FITNESS,
        HealthDataType.FITNESS_INACTIVE: DomainName.FITNESS,
        HealthDataType.PROFILE: DomainName.PROFILE,
        HealthDataType.DOCUMENTS: DomainName.DOCUMENTS,
    }

    def __init__(self, playbook_loader: PlaybookLoader | None = None):
        self.playbook_loader = playbook_loader or PlaybookLoader()

    def build_intent_plan(self, intent, conversation_context: ConversationContext) -> IntentPlan:
        domains = self._domains_from_intent(getattr(intent, "data_types", []))
        if not domains:
            domains = list(conversation_context.inherited_domains)
        mode = self._resolve_response_mode(conversation_context.user_message)
        clarifying_required = not getattr(intent, "is_ready", False)
        if clarifying_required:
            mode = ResponseMode.CLARIFY
        notes = []
        if conversation_context.message_kind != ConversationMessageKind.FRESH_QUERY:
            notes.append(f"Inherited from conversation: {conversation_context.message_kind.value}")
        return IntentPlan(
            domains=domains,
            response_mode=mode,
            confidence=float(getattr(intent, "confidence", 0.0) or 0.0),
            clarifying_required=clarifying_required,
            inherited_from_context=bool(conversation_context.inherited_domains),
            has_temporal_scope=bool(
                getattr(intent, "date_range", None)
                or getattr(intent, "month_filters", None)
                or conversation_context.inherited_date_scope
            ),
            requested_goal=conversation_context.inherited_goal,
            date_scope_label=conversation_context.inherited_date_scope,
            notes=notes,
        )

    def build_retrieval_plan(self, intent_plan: IntentPlan) -> RetrievalPlan:
        enrichment_domains: List[DomainName] = []
        use_patient_summary = len(intent_plan.domains) > 1 and intent_plan.response_mode in {
            ResponseMode.SUMMARIZE,
            ResponseMode.EVALUATE,
        }
        if any(
            domain in {DomainName.SLEEP, DomainName.VITALS, DomainName.PATIENT_SUMMARY}
            for domain in intent_plan.domains
        ):
            use_patient_summary = True
        if intent_plan.response_mode in {ResponseMode.EVALUATE, ResponseMode.RECOMMEND}:
            if DomainName.MEAL in intent_plan.domains and DomainName.CGM not in intent_plan.domains:
                enrichment_domains.append(DomainName.CGM)
            if DomainName.MEAL in intent_plan.domains and DomainName.FITNESS not in intent_plan.domains:
                enrichment_domains.append(DomainName.FITNESS)
        playbooks = self.playbook_loader.select(
            domains=intent_plan.domains,
            response_mode=intent_plan.response_mode,
            goal=intent_plan.requested_goal,
        )
        use_mongo_reports = self._should_use_mongo_reports(intent_plan)
        use_qdrant = any(
                domain in self.QDRANT_BACKED_DOMAINS for domain in intent_plan.domains
        ) and not use_mongo_reports
        tool_chain: list[str] = []
        if use_mongo_reports:
            tool_chain.append("mongo_report_fetch")
        if use_qdrant:
            tool_chain.append("qdrant_search")
        if use_patient_summary:
            tool_chain.append("patient_summary_fetch")

        return RetrievalPlan(
            primary_domains=intent_plan.domains,
            enrichment_domains=enrichment_domains,
            use_patient_summary=use_patient_summary,
            use_qdrant=use_qdrant,
            use_raw_payloads=not use_mongo_reports,
            result_limit=self._default_result_limit(intent_plan.response_mode),
            lookback_days=self._default_lookback_days(intent_plan.date_scope_label, intent_plan.response_mode),
            playbooks=[playbook.name for playbook in playbooks],
            tool_chain=tool_chain,
            notes=intent_plan.notes,
        )

    def _domains_from_intent(self, data_types: Iterable) -> List[DomainName]:
        found: list[DomainName] = []
        for data_type in data_types:
            domain = self.DATA_TYPE_TO_DOMAIN.get(data_type)
            if domain and domain not in found:
                found.append(domain)
        return found

    @staticmethod
    def _resolve_response_mode(message: str) -> ResponseMode:
        lowered = message.lower()
        if any(token in lowered for token in ["compare", "vs", "versus"]):
            return ResponseMode.COMPARE
        if any(token in lowered for token in ["thought", "how's", "how is", "evaluate", "good", "bad"]):
            return ResponseMode.EVALUATE
        if any(token in lowered for token in ["recommend", "should", "improve", "fix"]):
            return ResponseMode.RECOMMEND
        if any(token in lowered for token in ["show", "list", "what did i", "logged"]):
            return ResponseMode.LIST
        return ResponseMode.SUMMARIZE

    @staticmethod
    def _default_lookback_days(date_scope: str | None, response_mode: ResponseMode) -> int | None:
        if not date_scope:
            return 14 if response_mode in {ResponseMode.EVALUATE, ResponseMode.RECOMMEND} else None
        if "today" in date_scope or "yesterday" in date_scope:
            return 1
        if "week" in date_scope:
            return 7
        if "month" in date_scope:
            return 30
        if "4 days" in date_scope:
            return 4
        return None

    @staticmethod
    def _default_result_limit(response_mode: ResponseMode) -> int:
        if response_mode == ResponseMode.LIST:
            return 48
        if response_mode == ResponseMode.COMPARE:
            return 32
        if response_mode == ResponseMode.EVALUATE:
            return 24
        if response_mode == ResponseMode.RECOMMEND:
            return 18
        if response_mode == ResponseMode.SUMMARIZE:
            return 16
        return 12

    def _should_use_mongo_reports(self, intent_plan: IntentPlan) -> bool:
        if not intent_plan.has_temporal_scope:
            return False
        if not intent_plan.domains:
            return False
        if not set(intent_plan.domains).issubset(self.MONGO_REPORT_BACKED_DOMAINS):
            return False
        return intent_plan.response_mode in {
            ResponseMode.LIST,
            ResponseMode.SUMMARIZE,
            ResponseMode.COMPARE,
        }
