"""Care Intents v1 — structurer, service expiry, context injection, API gate.

Runs the real code paths: real structurer prompt assembly (gateway stubbed at
the boundary), real service logic on a fake session, real monitor/loader
section builders, real router function with stubbed dependencies.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from lib.ai_foundation.care_intents.contracts import (
    IntentCadence,
    IntentDomain,
    IntentType,
    StructuredCareIntent,
)
from lib.ai_foundation.care_intents.structurer import _SYSTEM_PROMPT, structure_care_intent
from lib.services.care_intent_service import CareIntentService


def _structured(**over) -> StructuredCareIntent:
    base = dict(
        intent_type=IntentType.REMIND,
        domain=IntentDomain.FITNESS,
        trigger_condition="no walk logged within 2h after dinner",
        cadence=IntentCadence.DAILY,
        patient_summary="Your care team would love to see a short walk after dinner.",
        review_days=14,
    )
    base.update(over)
    return StructuredCareIntent(**base)


# ── Structurer ───────────────────────────────────────────────────────────────


class TestStructurer:
    def test_prompt_derives_all_enums(self):
        """No hardcoded value lists — every enum member appears in the prompt."""
        for enum in (IntentType, IntentDomain, IntentCadence):
            for member in enum:
                assert member.value in _SYSTEM_PROMPT, f"{member} missing from prompt"

    @pytest.mark.asyncio
    async def test_structures_provider_sentence(self):
        gateway = MagicMock()
        gateway.extract = AsyncMock(return_value=(_structured(), None))
        result = await structure_care_intent(gateway, "  keep reminding him to walk after dinner  ")
        assert result.intent_type is IntentType.REMIND
        # Provider text reaches the LLM stripped, as the user message
        messages = gateway.extract.call_args.kwargs["messages"]
        assert messages[1]["content"] == "keep reminding him to walk after dinner"

    @pytest.mark.asyncio
    async def test_gateway_failure_propagates(self):
        """Never store a half-structured intent — errors surface to the API edge."""
        gateway = MagicMock()
        gateway.extract = AsyncMock(side_effect=RuntimeError("provider down"))
        with pytest.raises(RuntimeError):
            await structure_care_intent(gateway, "watch his morning readings")


# ── Service: lazy expiry on the AI read path ────────────────────────────────


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.committed = False

    async def scalars(self, stmt):
        return _FakeScalars(self._rows)

    async def commit(self):
        self.committed = True


def _row(days_until_review: int, author="Dr. Mehta"):
    return SimpleNamespace(
        author_name=author,
        author_role="Doctor",
        original_text="Walk after dinner",
        intent_type="remind",
        domain="fitness",
        trigger_condition="no walk after dinner",
        cadence="daily",
        review_date=date.today() + timedelta(days=days_until_review),
        status="active",
    )


class TestGetActiveContext:
    @pytest.mark.asyncio
    async def test_serves_fresh_expires_stale(self):
        fresh, stale = _row(5), _row(-1, author="Dr. Old")
        session = _FakeSession([fresh, stale])
        svc = CareIntentService(postgres_store=None)

        out = await svc.get_active_context(str(uuid4()), postgres_session=session)

        assert [c["author_name"] for c in out] == ["Dr. Mehta"]
        assert stale.status == "expired"
        assert session.committed  # expiry persisted
        assert set(out[0]) == {
            "author_name", "author_role", "original_text",
            "intent_type", "domain", "trigger_condition", "cadence",
        }

    @pytest.mark.asyncio
    async def test_all_fresh_no_commit(self):
        session = _FakeSession([_row(5)])
        svc = CareIntentService(postgres_store=None)
        out = await svc.get_active_context(str(uuid4()), postgres_session=session)
        assert len(out) == 1
        assert not session.committed


# ── Monitor + chat context injection ─────────────────────────────────────────


class _FakeReader:
    def __init__(self, intents=None, raises=False):
        self._intents = intents or []
        self._raises = raises

    async def get_active_context(self, patient_id):
        if self._raises:
            raise ConnectionError("db down")
        return self._intents


_INTENT_DICT = {
    "author_name": "Dr. Mehta",
    "author_role": "Doctor",
    "original_text": "Keep reminding him to walk after dinner",
    "intent_type": "remind",
    "domain": "fitness",
    "trigger_condition": "no walk logged within 2h after dinner",
    "cadence": "daily",
}


class TestMonitorInjection:
    def _agent(self, reader):
        from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent

        return ProactiveMonitorAgent(
            gateway=MagicMock(), qdrant=MagicMock(), care_intents=reader,
        )

    @pytest.mark.asyncio
    async def test_section_is_attributed(self):
        agent = self._agent(_FakeReader([_INTENT_DICT]))
        text = await agent._load_care_intents("p1")
        assert "CARE TEAM FOCUS" in text
        assert "[Dr. Mehta, Doctor]" in text
        assert "walk after dinner" in text
        assert "(when: no walk logged within 2h after dinner)" in text

    @pytest.mark.asyncio
    async def test_no_reader_or_empty_is_silent(self):
        assert await self._agent(None)._load_care_intents("p1") == ""
        assert await self._agent(_FakeReader([]))._load_care_intents("p1") == ""

    @pytest.mark.asyncio
    async def test_reader_failure_degrades_to_empty(self):
        assert await self._agent(_FakeReader(raises=True))._load_care_intents("p1") == ""


class TestChatInjection:
    @pytest.mark.asyncio
    async def test_loader_populates_context(self):
        from lib.ai_foundation.agents.core.context_loader import ContextLoader

        loader = ContextLoader(care_intents=_FakeReader([_INTENT_DICT]))
        intents = await loader._load_care_intents("p1")
        assert intents == [_INTENT_DICT]

    def test_context_messages_render_attributed_section(self):
        from lib.ai_foundation.agents.core.context_loader import (
            AgentContext,
            build_context_messages,
        )

        ctx = AgentContext(care_intents=[_INTENT_DICT])
        msgs = build_context_messages(
            user_message="hi", system_prompt="s", reasoning_prompt="r", context=ctx,
        )
        content = next(
            m["content"] for m in msgs if m.get("_meta", {}).get("type") == "context"
        )
        assert "CARE TEAM FOCUS" in content
        assert "Dr. Mehta asked you to" in content  # attribution instruction
        assert "never police" in content

    def test_no_intents_no_section(self):
        from lib.ai_foundation.agents.core.context_loader import (
            AgentContext,
            build_context_messages,
        )

        msgs = build_context_messages(
            user_message="hi", system_prompt="s", reasoning_prompt="r",
            context=AgentContext(),
        )
        joined = " ".join(m["content"] for m in msgs)
        assert "CARE TEAM FOCUS" not in joined


# ── API: safety gate + dry run (real router function, stubbed deps) ─────────


class TestCreateEndpoint:
    def _actor(self):
        return SimpleNamespace(model=SimpleNamespace(
            care_provider_id=uuid4(), role="Doctor", full_name="Dr. Mehta",
        ))

    def _payload(self, **over):
        import importlib

        CareIntentCreateRequest = importlib.import_module(
            "rest_server.v1.care_intents.router"
        ).CareIntentCreateRequest

        base = dict(patient_id=uuid4(), text="keep reminding him to walk after dinner")
        base.update(over)
        return CareIntentCreateRequest(**base)

    @pytest.mark.asyncio
    async def test_safety_flagged_rejected_not_stored(self, monkeypatch):
        import importlib

        router = importlib.import_module("rest_server.v1.care_intents.router")

        monkeypatch.setattr(
            router, "resolve_patient_access", AsyncMock(return_value=uuid4()),
        )
        service = MagicMock()
        service.create = AsyncMock()
        flagged = _structured(
            safety_flag=True, safety_reason="Changes metformin dosing",
        )
        with pytest.raises(HTTPException) as exc:
            await router.create_care_intent(
                payload=self._payload(structured=flagged),
                current_actor=self._actor(),
                access=MagicMock(),
                service=service,
                gateway=MagicMock(),
            )
        assert exc.value.status_code == 422
        assert "metformin" in exc.value.detail.lower()
        service.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_structures_without_saving(self, monkeypatch):
        import importlib

        router = importlib.import_module("rest_server.v1.care_intents.router")

        monkeypatch.setattr(
            router, "resolve_patient_access", AsyncMock(return_value=uuid4()),
        )
        monkeypatch.setattr(
            router, "structure_care_intent", AsyncMock(return_value=_structured()),
        )
        service = MagicMock()
        service.create = AsyncMock()
        resp = await router.create_care_intent(
            payload=self._payload(dry_run=True),
            current_actor=self._actor(),
            access=MagicMock(),
            service=service,
            gateway=MagicMock(),
        )
        assert resp.data["structured"]["intent_type"] == "remind"
        service.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_persists_with_attribution(self, monkeypatch):
        import importlib

        router = importlib.import_module("rest_server.v1.care_intents.router")

        pid = uuid4()
        monkeypatch.setattr(
            router, "resolve_patient_access", AsyncMock(return_value=pid),
        )
        monkeypatch.setattr(
            router, "structure_care_intent", AsyncMock(return_value=_structured()),
        )
        actor = self._actor()
        stored = SimpleNamespace(
            care_intent_id=uuid4(), patient_id=pid,
            author_id=actor.model.care_provider_id, author_role="Doctor",
            author_name="Dr. Mehta",
            original_text="keep reminding him to walk after dinner",
            intent_type="remind", domain="fitness",
            trigger_condition="no walk logged within 2h after dinner",
            cadence="daily", patient_summary="x", success_criteria=None,
            review_date=date.today() + timedelta(days=14), status="active",
            created_at=datetime.now(),
        )
        service = MagicMock()
        service.create = AsyncMock(return_value=stored)
        resp = await router.create_care_intent(
            payload=self._payload(),
            current_actor=actor,
            access=MagicMock(),
            service=service,
            gateway=MagicMock(),
        )
        kwargs = service.create.call_args.kwargs
        assert kwargs["author_name"] == "Dr. Mehta"
        assert kwargs["patient_id"] == pid
        assert resp.data["care_intent"]["author_name"] == "Dr. Mehta"
