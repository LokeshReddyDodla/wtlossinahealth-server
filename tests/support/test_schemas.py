"""Pydantic-layer validation tests for support ticket request schemas."""

from __future__ import annotations

import pytest

# Warm up import graph (see other support tests for context).
import lib.models  # noqa: F401,E402
from lib.models.patient import Patient  # noqa: F401,E402

from lib.schemas.support_ticket import (  # noqa: E402
    SupportAgentReplyRequest,
    SupportTicketOpenRequest,
    SupportTicketStatusUpdateRequest,
)


# --- SupportTicketOpenRequest --------------------------------------------


def test_open_request_product_scope_does_not_require_facility():
    req = SupportTicketOpenRequest(scope="product", initial_message="help")
    assert req.scope == "product"
    assert req.health_facility_id is None


def test_open_request_facility_scope_without_facility_id_raises():
    with pytest.raises(ValueError, match="health_facility_id is required"):
        SupportTicketOpenRequest(scope="facility", initial_message="help")


def test_open_request_facility_with_facility_id_ok():
    req = SupportTicketOpenRequest(
        scope="facility",
        initial_message="help",
        health_facility_id="f-1",
    )
    assert req.health_facility_id == "f-1"


def test_open_request_rejects_empty_initial_message():
    with pytest.raises(ValueError):
        SupportTicketOpenRequest(scope="product", initial_message="")


def test_open_request_rejects_overly_long_message():
    with pytest.raises(ValueError):
        SupportTicketOpenRequest(
            scope="product", initial_message="x" * 5000
        )


def test_open_request_rejects_invalid_scope():
    with pytest.raises(ValueError):
        SupportTicketOpenRequest(
            scope="random",  # type: ignore[arg-type]
            initial_message="hi",
        )


# --- SupportTicketStatusUpdateRequest ------------------------------------


@pytest.mark.parametrize(
    "status", ["open", "pending", "resolved", "closed"]
)
def test_status_update_accepts_valid_status(status):
    req = SupportTicketStatusUpdateRequest(status=status)
    assert req.status == status


def test_status_update_rejects_invalid_status():
    with pytest.raises(ValueError):
        SupportTicketStatusUpdateRequest(
            status="random"  # type: ignore[arg-type]
        )


# --- SupportAgentReplyRequest --------------------------------------------


def test_agent_reply_rejects_empty_content():
    with pytest.raises(ValueError):
        SupportAgentReplyRequest(content="")


def test_agent_reply_ok_with_content():
    req = SupportAgentReplyRequest(content="resolved on our end")
    assert req.content == "resolved on our end"
    assert req.media is None


# --- assistant sub-document -----------------------------------------------


def test_ticket_schema_accepts_assistant_state_and_defaults_to_none():
    from lib.schemas.support_ticket import SupportTicketSchema

    bare = SupportTicketSchema(
        chat_id="c1", scope="product", requester_id="p1", requester_type="patient"
    )
    assert bare.assistant is None

    with_bot = SupportTicketSchema(
        chat_id="c1",
        scope="product",
        requester_id="p1",
        requester_type="patient",
        assistant={
            "category": "cgm_sensor",
            "urgency": "high",
            "needs_human": True,
            "summary": "Sensor replacement.",
            "handling_mode": "held_for_human",
            "reply_count": 2,
        },
    )
    assert with_bot.assistant.category.value == "cgm_sensor"
    assert with_bot.assistant.handling_mode.value == "held_for_human"
    assert with_bot.assistant.reply_count == 2


def test_ticket_schema_rejects_unknown_assistant_category():
    import pytest as _pytest

    from lib.schemas.support_ticket import SupportTicketSchema

    with _pytest.raises(ValueError):
        SupportTicketSchema(
            chat_id="c1", scope="product", requester_id="p1", requester_type="patient",
            assistant={"category": "made_up"},
        )


def test_every_ai_feature_has_an_admin_label():
    """The admin AI-features page indexes ``_LABELS`` by enum member; a new
    feature without a label 500s the whole page."""
    from lib.core.constants import AIFeatureEnum
    from rest_server.v1.admin.ai_features.read import _LABELS

    assert set(_LABELS) == set(AIFeatureEnum)
