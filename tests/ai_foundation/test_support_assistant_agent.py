"""Support Assistant agent — policy layer, snapshot rendering, templates.

The gateway is mocked: ``extract`` returns a canned ``SupportTriage`` so
each test drives one handling mode. The policy under test is that the
category decides what the patient sees, regardless of the model's reply.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from lib.ai_foundation.agents.state import AgentContext, AgentInput
from lib.ai_foundation.agents.support_assistant import (
    HandlingMode,
    SupportAssistantAgent,
    SupportCategory,
    SupportSnapshot,
    SupportTriage,
    SupportUrgency,
)
from lib.ai_foundation.agents.support_assistant.agent import (
    EMERGENCY_MESSAGE,
    HOLD_MESSAGE,
    HOLD_MESSAGE_AFTER_FAILURE,
    MEDICAL_REDIRECT_NO_CONTACT,
    MEDICAL_REDIRECT_WITH_CONTACT,
    render_snapshot,
)
from lib.ai_foundation.agents.support_assistant.contracts import (
    CareTeamContact,
    DeviceSyncState,
    FacilityContact,
    PermissionState,
)
from lib.ai_foundation.models.registry import ModelTask

_LF = {
    "set_langfuse_context": lambda **k: None,
    "langfuse_trace_input": lambda **k: None,
    "langfuse_trace_output": lambda **k: None,
}


def _meta():
    return SimpleNamespace(cost=SimpleNamespace(total_cost=0.0002), model_id="test-model")


def _gateway(triage: SupportTriage | Exception):
    async def extract(*, task, **_):
        assert task == ModelTask.SUPPORT_ASSISTANT
        if isinstance(triage, Exception):
            raise triage
        return triage, _meta()

    return SimpleNamespace(extract=AsyncMock(side_effect=extract), **_LF)


def _triage(category, *, reply="Here is the fix.", needs_human=False, urgency="normal"):
    return SupportTriage(
        category=category,
        urgency=urgency,
        needs_human=needs_human,
        summary="Patient asked about X.",
        reply=reply,
    )


def _snapshot(**overrides) -> SupportSnapshot:
    base = dict(
        patient_first_name="Asha",
        timezone="Asia/Kolkata",
        language="en",
        facility=FacilityContact(
            name="Sunrise Clinic", phone="+911111", emergency_phone="+919999", operating_hours="9-6"
        ),
        care_team=[
            CareTeamContact(name="Dr Rao", role="Doctor", phone="+912222", email="rao@x.in"),
            CareTeamContact(name="Priya", role="Dietitian", phone=None, email="p@x.in", is_active=False),
        ],
        permissions=PermissionState(
            notifications=True, health=False, camera=False, gallery=True, storage=True,
            synced_at=datetime(2026, 9, 9, 10, 0),
        ),
        glucose_sources=[
            DeviceSyncState(
                provider="LibreView (FreeStyle Libre)", sync_status="active",
                last_sync_at=datetime(2026, 9, 9, 17, 2), last_reading_at=datetime(2026, 9, 9, 16, 55),
                live_polling_enabled=True, live_last_sync_at=None,
            )
        ],
        last_meal_date="2026-09-08",
        meals_last_7_days=4,
    )
    base.update(overrides)
    return SupportSnapshot(**base)


def _input(message="my camera does not work", *, snapshot=None, history=None, language=None):
    ctx = AgentContext(patient_id="p1", user_id="p1", thread_id="support:t1")
    if language:
        ctx.metadata["language"] = language
    meta = {}
    if snapshot is not None:
        meta["snapshot"] = snapshot.model_dump()
    if history is not None:
        meta["history"] = history
    return AgentInput(message=message, context=ctx, metadata=meta)


# --- policy --------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_serve_answer_is_sent_verbatim():
    gw = _gateway(_triage(SupportCategory.APP_PERMISSIONS, reply="1. Open Settings\n2. Manage Permissions"))
    out = await SupportAssistantAgent(gateway=gw).run(_input(snapshot=_snapshot()))

    assert out.message == "1. Open Settings\n2. Manage Permissions"
    assert out.data["handling_mode"] == HandlingMode.ANSWERED.value
    assert out.data["needs_human"] is False
    assert out.data["category"] == "app_permissions"
    assert out.cost_usd == pytest.approx(0.0002)
    assert out.model_id == "test-model"


@pytest.mark.asyncio
async def test_needs_human_appends_hold_message_after_ack():
    gw = _gateway(_triage(SupportCategory.CGM_SENSOR, reply="Sensor replacement needs the clinic.", needs_human=True))
    out = await SupportAssistantAgent(gateway=gw).run(_input(snapshot=_snapshot()))

    assert out.message.startswith("Sensor replacement needs the clinic.")
    assert out.message.endswith(HOLD_MESSAGE)
    assert out.data["handling_mode"] == HandlingMode.HELD_FOR_HUMAN.value
    assert out.data["needs_human"] is True


@pytest.mark.asyncio
async def test_non_self_serve_category_is_held_even_if_model_says_no_human():
    gw = _gateway(_triage(SupportCategory.BILLING_OR_PACKAGE, reply="Your package costs X.", needs_human=False))
    out = await SupportAssistantAgent(gateway=gw).run(_input(snapshot=_snapshot()))

    assert out.data["handling_mode"] == HandlingMode.HELD_FOR_HUMAN.value
    assert out.data["needs_human"] is True
    assert HOLD_MESSAGE in out.message


@pytest.mark.asyncio
async def test_empty_reply_on_self_serve_category_falls_back_to_hold():
    gw = _gateway(_triage(SupportCategory.MEAL_LOGGING, reply="   "))
    out = await SupportAssistantAgent(gateway=gw).run(_input(snapshot=_snapshot()))

    assert out.message == HOLD_MESSAGE
    assert out.data["needs_human"] is True


@pytest.mark.asyncio
async def test_medical_question_redirects_with_active_care_team_contacts():
    gw = _gateway(_triage(SupportCategory.MEDICAL_QUESTION, reply="I can't advise on doses.", needs_human=True))
    out = await SupportAssistantAgent(gateway=gw).run(_input(snapshot=_snapshot()))

    assert out.data["handling_mode"] == HandlingMode.REDIRECTED_MEDICAL.value
    assert MEDICAL_REDIRECT_WITH_CONTACT in out.message
    assert "Dr Rao (Doctor) — +912222 — rao@x.in" in out.message
    # Inactive provider is dropped when at least one active contact exists.
    assert "Priya" not in out.message


@pytest.mark.asyncio
async def test_medical_question_without_care_team_points_to_chat():
    gw = _gateway(_triage(SupportCategory.MEDICAL_QUESTION, reply="Ask your care team.", needs_human=True))
    out = await SupportAssistantAgent(gateway=gw).run(_input(snapshot=_snapshot(care_team=[])))

    assert MEDICAL_REDIRECT_NO_CONTACT in out.message


@pytest.mark.asyncio
async def test_emergency_drops_model_reply_and_includes_numbers():
    gw = _gateway(_triage(SupportCategory.EMERGENCY, reply="SHOULD NOT APPEAR", needs_human=True, urgency="urgent"))
    out = await SupportAssistantAgent(gateway=gw).run(_input("chest pain", snapshot=_snapshot()))

    assert out.data["handling_mode"] == HandlingMode.EMERGENCY.value
    assert out.data["urgency"] == SupportUrgency.URGENT.value
    assert out.message.startswith(EMERGENCY_MESSAGE)
    assert "+919999" in out.message           # facility emergency phone
    assert "Dr Rao (Doctor) — +912222" in out.message
    assert "Priya" not in out.message          # no phone -> not a usable emergency contact
    assert "SHOULD NOT APPEAR" not in out.message


@pytest.mark.asyncio
async def test_llm_failure_still_sends_honest_hold_and_flags_human():
    gw = _gateway(RuntimeError("provider down"))
    out = await SupportAssistantAgent(gateway=gw).run(_input(snapshot=_snapshot()))

    assert out.is_ready is False
    assert out.message == HOLD_MESSAGE_AFTER_FAILURE
    assert out.data["needs_human"] is True
    assert out.data["error"] is True
    assert out.data["category"] == SupportCategory.UNKNOWN.value


# --- translation of templates ---------------------------------------------


@pytest.mark.asyncio
async def test_templates_are_translated_but_contacts_are_not():
    translator = SimpleNamespace(
        translate_cached=AsyncMock(side_effect=lambda text, lang, **_: f"[{lang}] {text}")
    )
    gw = _gateway(_triage(SupportCategory.EMERGENCY, reply="", needs_human=True, urgency="urgent"))
    agent = SupportAssistantAgent(gateway=gw, translator=translator)
    out = await agent.run(_input("emergency", snapshot=_snapshot(language="hi")))

    assert out.message.startswith(f"[hi] {EMERGENCY_MESSAGE}")
    assert "+919999" in out.message
    assert out.data["language"] == "hi"


@pytest.mark.asyncio
async def test_explicit_language_overrides_snapshot_language():
    translator = SimpleNamespace(translate_cached=AsyncMock(side_effect=lambda text, lang, **_: f"[{lang}] {text}"))
    gw = _gateway(_triage(SupportCategory.COMPLAINT, reply="Sorry about that.", needs_human=True))
    agent = SupportAssistantAgent(gateway=gw, translator=translator)
    out = await agent.run(_input(snapshot=_snapshot(language="hi"), language="ta"))

    assert out.message.endswith(f"[ta] {HOLD_MESSAGE}")


@pytest.mark.asyncio
async def test_translator_failure_falls_back_to_english_template():
    translator = SimpleNamespace(translate_cached=AsyncMock(side_effect=RuntimeError("boom")))
    gw = _gateway(_triage(SupportCategory.COMPLAINT, reply="Sorry.", needs_human=True))
    out = await SupportAssistantAgent(gateway=gw, translator=translator).run(
        _input(snapshot=_snapshot(language="hi"))
    )
    assert out.message.endswith(HOLD_MESSAGE)


# --- prompt assembly ---------------------------------------------------------


@pytest.mark.asyncio
async def test_messages_carry_brain_snapshot_language_and_history():
    gw = _gateway(_triage(SupportCategory.GENERAL_FAQ))
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "system", "content": "ignored"},
        {"role": "user", "content": ""},
    ]
    await SupportAssistantAgent(gateway=gw).run(
        _input("where are reports?", snapshot=_snapshot(language="hi"), history=history)
    )

    messages = gw.extract.await_args.kwargs["messages"]
    assert messages[0]["role"] == "system" and "KNOWLEDGE BASE" in messages[0]["content"]
    assert "PATIENT SNAPSHOT" in messages[1]["content"]
    assert "Hindi" in messages[2]["content"] and "hi" in messages[2]["content"]
    assert messages[3:5] == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert messages[-1] == {"role": "user", "content": "where are reports?"}


@pytest.mark.asyncio
async def test_missing_or_malformed_snapshot_renders_as_unavailable():
    gw = _gateway(_triage(SupportCategory.GENERAL_FAQ))
    inp = _input()
    inp.metadata["snapshot"] = {"care_team": "not-a-list"}
    await SupportAssistantAgent(gateway=gw).run(inp)

    snapshot_text = gw.extract.await_args.kwargs["messages"][1]["content"]
    assert "could not be checked" in snapshot_text


# --- snapshot rendering ------------------------------------------------------


def test_render_snapshot_states_permissions_sync_and_contacts():
    text = render_snapshot(_snapshot())
    assert "Camera OFF" in text and "Health OFF" in text and "Gallery ON" in text
    assert "Dr Rao (Doctor) — +912222 — rao@x.in" in text
    assert "Priya (Dietitian) — p@x.in [currently unavailable]" in text
    assert "emergency phone +919999" in text
    assert "last sync 09 Sep 2026, 17:02" in text
    assert "live polling on" in text
    assert "Last saved meal: 2026-09-08; meals saved in the last 7 days: 4" in text


def test_render_snapshot_marks_failed_sections():
    text = render_snapshot(SupportSnapshot(lookup_errors=["permissions", "glucose_sources"]))
    assert text.count("could not be checked") == 2
    assert "No care provider is assigned" in text
    assert "No device registered" in text


@pytest.mark.asyncio
async def test_medical_redirect_not_duplicated_when_model_already_listed_contacts():
    gw = _gateway(_triage(
        SupportCategory.MEDICAL_QUESTION,
        reply="I can't advise on insulin. Please call Dr Rao on +912222.",
        needs_human=True,
    ))
    out = await SupportAssistantAgent(gateway=gw).run(_input(snapshot=_snapshot()))

    assert out.message == "I can't advise on insulin. Please call Dr Rao on +912222."
    assert MEDICAL_REDIRECT_WITH_CONTACT not in out.message
    assert out.data["handling_mode"] == HandlingMode.REDIRECTED_MEDICAL.value
    assert out.data["needs_human"] is True
