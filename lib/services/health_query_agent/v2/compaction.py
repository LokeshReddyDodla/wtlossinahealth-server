from __future__ import annotations

from typing import Iterable, Optional

from .models import ConversationCompaction, ConversationContext, DomainName, ThreadState


def build_conversation_compaction(
    *,
    thread_id: str,
    patient_id: Optional[str],
    recent_messages: Iterable[dict],
    thread_state: Optional[ThreadState],
    conversation_context: Optional[ConversationContext] = None,
) -> ConversationCompaction:
    messages = list(recent_messages)[-12:]
    user_turns = [msg.get("content", "") for msg in messages if msg.get("message_type") == "user" or msg.get("role") == "user"]
    assistant_turns = [msg.get("content", "") for msg in messages if msg.get("message_type") == "assistant" or msg.get("role") == "assistant"]

    summary_parts: list[str] = []
    if thread_state and thread_state.active_goal:
        summary_parts.append(f"goal={thread_state.active_goal}")
    if thread_state and thread_state.active_date_scope:
        summary_parts.append(f"date_scope={thread_state.active_date_scope}")
    if thread_state and thread_state.active_domains:
        summary_parts.append(
            "domains=" + ",".join(domain.value for domain in thread_state.active_domains)
        )
    if user_turns:
        summary_parts.append(f"last_user={user_turns[-1][:140]}")
    if assistant_turns:
        summary_parts.append(f"last_assistant={assistant_turns[-1][:140]}")
    if conversation_context and conversation_context.compaction_summary:
        summary_parts.append(f"prior={conversation_context.compaction_summary[:140]}")

    domains = (
        thread_state.active_domains
        if thread_state and thread_state.active_domains
        else conversation_context.inherited_domains
        if conversation_context
        else []
    )

    return ConversationCompaction(
        thread_id=thread_id,
        patient_id=patient_id,
        summary=" | ".join(summary_parts)[:1000],
        domains=[DomainName(domain.value) if not isinstance(domain, DomainName) else domain for domain in domains],
        active_goal=thread_state.active_goal if thread_state else conversation_context.inherited_goal if conversation_context else None,
        active_date_scope=thread_state.active_date_scope if thread_state else conversation_context.inherited_date_scope if conversation_context else None,
        turn_count=sum(
            1
            for msg in messages
            if msg.get("message_type") == "user" or msg.get("role") == "user"
        ),
    )
