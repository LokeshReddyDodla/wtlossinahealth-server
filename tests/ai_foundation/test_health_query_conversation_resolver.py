from lib.services.health_query_agent.v2.conversation_resolver import ConversationResolver
from lib.services.health_query_agent.v2.models import (
    ConversationMessageKind,
    DomainName,
    ThreadState,
)


def test_inbody_query_maps_to_documents_domain():
    context = ConversationResolver.resolve(
        user_message="give patients inbody details",
        recent_messages=[],
        thread_state=None,
        patient_memory=[],
    )

    assert DomainName.DOCUMENTS in context.inherited_domains
    assert context.message_kind == ConversationMessageKind.FRESH_QUERY


def test_inbody_query_overrides_unrelated_thread_domain():
    thread_state = ThreadState(
        thread_id="t1",
        active_domains=[DomainName.FITNESS],
    )

    context = ConversationResolver.resolve(
        user_message="inbody details",
        recent_messages=[],
        thread_state=thread_state,
        patient_memory=[],
    )

    assert context.inherited_domains == [DomainName.DOCUMENTS]
