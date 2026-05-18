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
