from __future__ import annotations

import re
from typing import Iterable, List, Optional

from .conversation_lexicon import ConversationLexiconLoader
from .models import (
    ConversationCompaction,
    ConversationContext,
    ConversationMessageKind,
    DomainName,
    PatientMemoryFact,
    ThreadState,
)


class ConversationResolver:
    lexicon_loader = ConversationLexiconLoader()

    @classmethod
    def resolve(
        cls,
        user_message: str,
        recent_messages: List[dict],
        thread_state: Optional[ThreadState],
        patient_memory: Iterable[PatientMemoryFact],
        latest_compaction: Optional[ConversationCompaction] = None,
    ) -> ConversationContext:
        lexicon = cls.lexicon_loader.load()
        normalized = " ".join(user_message.strip().split())
        lowered = normalized.lower()
        facts = cls._extract_explicit_facts(normalized)
        domains = cls._detect_domains(lowered, lexicon)
        goal = cls._detect_goal(lowered, lexicon)
        inherited_domains = list(thread_state.active_domains) if thread_state and thread_state.active_domains else list(latest_compaction.domains) if latest_compaction else []
        inherited_goal = goal or (thread_state.active_goal if thread_state and thread_state.active_goal else latest_compaction.active_goal if latest_compaction else None)
        inherited_date_scope = cls._detect_date_scope(lowered, lexicon) or (
            thread_state.active_date_scope if thread_state and thread_state.active_date_scope else latest_compaction.active_date_scope if latest_compaction else None
        )
        kind = cls._classify(lowered, domains, thread_state, lexicon)
        if not domains and inherited_domains and kind in {
            ConversationMessageKind.FOLLOW_UP,
            ConversationMessageKind.CLARIFICATION_ANSWER,
            ConversationMessageKind.GOAL_UPDATE,
        }:
            domains = inherited_domains
        notes = cls._build_notes(
            kind,
            thread_state,
            patient_memory,
            domains,
            inherited_goal,
            inherited_date_scope,
            latest_compaction,
        )
        return ConversationContext(
            message_kind=kind,
            user_message=user_message,
            normalized_message=normalized,
            recent_messages=recent_messages[-6:],
            inherited_domains=domains,
            inherited_goal=inherited_goal,
            inherited_date_scope=inherited_date_scope,
            pending_slots=list(thread_state.pending_slots) if thread_state else [],
            explicit_facts=facts,
            compaction_summary=latest_compaction.summary if latest_compaction else None,
            context_notes=notes,
        )

    @classmethod
    def _classify(
        cls,
        lowered: str,
        domains: List[DomainName],
        thread_state: Optional[ThreadState],
        lexicon,
    ) -> ConversationMessageKind:
        if lowered in lexicon.greetings or lowered in lexicon.acknowledgements:
            return ConversationMessageKind.CONVERSATIONAL
        if cls._detect_goal(lowered, lexicon):
            return ConversationMessageKind.GOAL_UPDATE
        if thread_state and thread_state.pending_slots and len(lowered.split()) <= 6:
            return ConversationMessageKind.CLARIFICATION_ANSWER
        if thread_state and len(lowered.split()) <= 8 and not domains:
            return ConversationMessageKind.FOLLOW_UP
        if thread_state and len(lowered.split()) <= 8 and domains:
            return ConversationMessageKind.FOLLOW_UP
        return ConversationMessageKind.FRESH_QUERY

    @classmethod
    def _detect_domains(cls, lowered: str, lexicon) -> List[DomainName]:
        found: list[DomainName] = []
        for domain_name, keywords in lexicon.domain_keywords.items():
            domain = DomainName(domain_name)
            if any(keyword in lowered for keyword in keywords):
                found.append(domain)
        return found

    @classmethod
    def _detect_goal(cls, lowered: str, lexicon) -> Optional[str]:
        for phrase, value in lexicon.goal_aliases.items():
            if phrase in lowered:
                return value
        return None

    @staticmethod
    def _detect_date_scope(lowered: str, lexicon) -> Optional[str]:
        for phrase, value in lexicon.date_aliases.items():
            if phrase in lowered:
                return value
        return None

    @classmethod
    def _extract_explicit_facts(cls, message: str) -> List[PatientMemoryFact]:
        lowered = message.lower()
        facts: list[PatientMemoryFact] = []
        goal = cls._detect_goal(lowered, cls.lexicon_loader.load())
        if goal:
            facts.append(PatientMemoryFact(key="goal", value=goal, source="user", confidence=1.0, confirmed=True))
        if "ramadan" in lowered or "fasting" in lowered:
            facts.append(PatientMemoryFact(key="fasting_context", value="ramadan", source="user", confidence=1.0, confirmed=True))
        weight_match = re.search(r"(\d{2,3}(?:\.\d+)?)\s?kg", lowered)
        if weight_match:
            facts.append(PatientMemoryFact(key="weight_kg", value=float(weight_match.group(1)), source="user", confidence=1.0, confirmed=True))
        if "before iftar" in lowered:
            facts.append(PatientMemoryFact(key="training_timing", value="before_iftar", source="user", confidence=1.0, confirmed=True))
        if "concise" in lowered or "chatgpt" in lowered:
            facts.append(PatientMemoryFact(key="communication_style", value="concise", source="user", confidence=1.0, confirmed=True))
        return facts

    @staticmethod
    def _build_notes(
        kind: ConversationMessageKind,
        thread_state: Optional[ThreadState],
        patient_memory: Iterable[PatientMemoryFact],
        domains: List[DomainName],
        goal: Optional[str],
        date_scope: Optional[str],
        latest_compaction: Optional[ConversationCompaction],
    ) -> List[str]:
        notes = [f"Conversation kind: {kind.value}."]
        if domains:
            notes.append("Active domains from context: " + ", ".join(domain.value for domain in domains) + ".")
        if goal:
            notes.append(f"Active goal: {goal}.")
        if date_scope:
            notes.append(f"Active date scope: {date_scope}.")
        if thread_state and thread_state.last_assistant_question:
            notes.append(f"Last assistant question: {thread_state.last_assistant_question}")
        if latest_compaction and latest_compaction.summary:
            notes.append(f"Latest thread compaction: {latest_compaction.summary}")
        facts = list(patient_memory)
        if facts:
            compact = ", ".join(f"{fact.key}={fact.value}" for fact in facts[:6])
            notes.append(f"Durable patient memory: {compact}.")
        return notes
