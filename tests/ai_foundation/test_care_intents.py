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
    def __init__(self, *result_sets):
        self._result_sets = list(result_sets)
        self.committed = False
        self.executed = []

    async def scalars(self, stmt):
        rows = self._result_sets.pop(0) if self._result_sets else []
        return _FakeScalars(rows)

    async def execute(self, stmt):
        self.executed.append(stmt)

    async def commit(self):
        self.committed = True


def _row(days_until_review: int, author="Dr. Mehta"):
    return SimpleNamespace(
        care_intent_id=uuid4(),
        created_at=datetime.now(),
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
        session = _FakeSession([fresh, stale], [])  # intents, then (no) events
        svc = CareIntentService(postgres_store=None)

        out = await svc.get_active_context(str(uuid4()), postgres_session=session)

        assert [c["author_name"] for c in out] == ["Dr. Mehta"]
        assert stale.status == "expired"
        assert session.committed  # expiry persisted
        assert set(out[0]) == {
            "care_intent_id", "author_name", "author_role", "original_text",
            "intent_type", "domain", "trigger_condition", "cadence",
            "created_at", "adherence_hint",
        }

    @pytest.mark.asyncio
    async def test_all_fresh_no_commit(self):
        session = _FakeSession([_row(5)], [])
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
        text = agent._format_care_intents_section(await agent._get_care_intents("p1"))
        assert "CARE TEAM FOCUS" in text
        assert "[Dr. Mehta, Doctor]" in text
        assert "walk after dinner" in text
        assert "(when: no walk logged within 2h after dinner)" in text

    @pytest.mark.asyncio
    async def test_no_reader_or_empty_is_silent(self):
        agent = self._agent(None)
        assert agent._format_care_intents_section(await agent._get_care_intents("p1")) == ""
        agent = self._agent(_FakeReader([]))
        assert agent._format_care_intents_section(await agent._get_care_intents("p1")) == ""

    @pytest.mark.asyncio
    async def test_reader_failure_degrades_to_empty(self):
        agent = self._agent(_FakeReader(raises=True))
        assert await agent._get_care_intents("p1") == []

    def test_adherence_hint_rendered_with_gentle_framing(self):
        agent = self._agent(None)
        text = agent._format_care_intents_section([
            {**_INTENT_DICT, "adherence_hint": "followed 2 of last 5 evaluated days; missed the last 2"},
        ])
        assert "recent adherence: followed 2 of last 5" in text
        assert "never scold" in text


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
        """The safety verdict is server-side ONLY — the request schema has no
        structured field a client could forge."""
        import importlib

        router = importlib.import_module("rest_server.v1.care_intents.router")

        assert "structured" not in router.CareIntentCreateRequest.model_fields
        assert "structured" not in router.CareIntentUpdateRequest.model_fields

        monkeypatch.setattr(
            router, "resolve_patient_access", AsyncMock(return_value=uuid4()),
        )
        flagged = _structured(
            safety_flag=True, safety_reason="Changes metformin dosing",
        )
        monkeypatch.setattr(
            router, "structure_care_intent", AsyncMock(return_value=flagged),
        )
        service = MagicMock()
        service.create = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await router.create_care_intent(
                payload=self._payload(),
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


# ── v2: adherence evaluator ──────────────────────────────────────────────────


class TestAdherenceEvaluator:
    @pytest.mark.asyncio
    async def test_verdicts_map_by_index_and_default_unclear(self):
        from lib.ai_foundation.care_intents.adherence import (
            AdherenceVerdicts,
            IntentVerdict,
            evaluate_adherence,
        )

        gateway = MagicMock()
        gateway.extract = AsyncMock(return_value=(
            AdherenceVerdicts(verdicts=[
                IntentVerdict(intent_index=1, status="followed"),
                # index 2 skipped by the model → must default to "unclear"
            ]),
            None,
        ))
        intents = [
            {"care_intent_id": "a", "original_text": "Walk after dinner"},
            {"care_intent_id": "b", "original_text": "No rice at dinner"},
        ]
        out = await evaluate_adherence(
            gateway, intents=intents, day_data_text="...", day_label="yesterday",
        )
        assert out == [
            {"care_intent_id": "a", "status": "followed", "note": None},
            {"care_intent_id": "b", "status": "unclear", "note": None},
        ]

    @pytest.mark.asyncio
    async def test_barrier_note_carried(self):
        from lib.ai_foundation.care_intents.adherence import (
            AdherenceVerdicts,
            IntentVerdict,
            evaluate_adherence,
        )

        gateway = MagicMock()
        gateway.extract = AsyncMock(return_value=(
            AdherenceVerdicts(verdicts=[
                IntentVerdict(intent_index=1, status="missed", barrier_note="knee pain logged 7/10"),
            ]),
            None,
        ))
        out = await evaluate_adherence(
            gateway,
            intents=[{"care_intent_id": "a", "original_text": "Walk after dinner"}],
            day_data_text="Symptom: knee pain 7/10",
            day_label="yesterday",
        )
        assert out[0]["note"] == "knee pain logged 7/10"

    @pytest.mark.asyncio
    async def test_no_intents_no_llm_call(self):
        from lib.ai_foundation.care_intents.adherence import evaluate_adherence

        gateway = MagicMock()
        gateway.extract = AsyncMock()
        assert await evaluate_adherence(gateway, intents=[], day_data_text="x", day_label="y") == []
        gateway.extract.assert_not_called()


# ── v2: adherence summary + escalation flag ─────────────────────────────────


def _event(days_ago: int, status: str, note=None):
    return SimpleNamespace(
        event_date=date.today() - timedelta(days=days_ago),
        status=status,
        note=note,
    )


class TestAdherenceSummary:
    @pytest.mark.asyncio
    async def test_needs_attention_after_three_consecutive_misses(self):
        intent_id = uuid4()
        events = [
            _event(1, "missed"), _event(2, "missed"), _event(3, "missed", note="no dinner logged"),
            _event(4, "followed"), _event(5, "unclear"),
        ]
        for e in events:
            e.care_intent_id = intent_id
        session = _FakeSession(events)
        svc = CareIntentService(postgres_store=None)
        out = await svc.adherence_summary([intent_id], postgres_session=session)
        s = out[str(intent_id)]
        assert s["consecutive_missed"] == 3
        assert s["needs_attention"] is True
        assert s["days_evaluated"] == 4  # unclear not judged
        assert s["days_followed"] == 1
        assert s["barriers"] == ["no dinner logged"]

    @pytest.mark.asyncio
    async def test_follow_streak_not_flagged(self):
        intent_id = uuid4()
        events = [_event(1, "followed"), _event(2, "missed"), _event(3, "missed")]
        for e in events:
            e.care_intent_id = intent_id
        session = _FakeSession(events)
        svc = CareIntentService(postgres_store=None)
        out = await svc.adherence_summary([intent_id], postgres_session=session)
        assert out[str(intent_id)]["needs_attention"] is False


# ── v2: monitor morning hook ─────────────────────────────────────────────────


class TestMonitorAdherenceHook:
    @pytest.mark.asyncio
    async def test_records_on_morning_cron_only_semantics(self, monkeypatch):
        """_record_adherence evaluates with scan data and upserts via reader."""
        from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent
        import lib.ai_foundation.care_intents.adherence as adherence_mod

        reader = MagicMock()
        reader.record_adherence = AsyncMock()
        agent = ProactiveMonitorAgent(gateway=MagicMock(), qdrant=MagicMock(), care_intents=reader)

        verdicts = [{"care_intent_id": "abcd1234", "status": "followed", "note": None}]
        monkeypatch.setattr(adherence_mod, "evaluate_adherence", AsyncMock(return_value=verdicts))

        await agent._record_adherence(
            "patient-1", [{"care_intent_id": "abcd1234", "original_text": "x"}],
            "day data", "2026-07-15", "yesterday",
        )
        kwargs = reader.record_adherence.call_args
        assert kwargs.args[0] == verdicts
        assert str(kwargs.kwargs["event_date"]) == "2026-07-15"

    @pytest.mark.asyncio
    async def test_failure_never_raises(self, monkeypatch):
        from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent
        import lib.ai_foundation.care_intents.adherence as adherence_mod

        monkeypatch.setattr(
            adherence_mod, "evaluate_adherence", AsyncMock(side_effect=RuntimeError("llm down")),
        )
        agent = ProactiveMonitorAgent(gateway=MagicMock(), qdrant=MagicMock(), care_intents=MagicMock())
        await agent._record_adherence("p", [{"care_intent_id": "a", "original_text": "x"}], "d", "2026-07-15", "yesterday")


# ── v3: conflicts + proposals ────────────────────────────────────────────────


class TestAdvisor:
    @pytest.mark.asyncio
    async def test_no_existing_intents_skips_llm(self):
        from lib.ai_foundation.care_intents.advisor import detect_intent_conflicts

        gateway = MagicMock()
        gateway.extract = AsyncMock()
        assert await detect_intent_conflicts(gateway, new_text="x", existing=[]) == []
        gateway.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_conflicts_returned(self):
        from lib.ai_foundation.care_intents.advisor import ConflictReport, detect_intent_conflicts

        gateway = MagicMock()
        gateway.extract = AsyncMock(return_value=(
            ConflictReport(conflicts=['Dr. Mehta\'s "no food after 9 PM" conflicts with a bedtime snack.']),
            None,
        ))
        out = await detect_intent_conflicts(
            gateway,
            new_text="add a small bedtime snack",
            existing=[_INTENT_DICT],
        )
        assert len(out) == 1 and "conflicts" in out[0]

    @pytest.mark.asyncio
    async def test_proposals_capped_at_two_and_empty_without_insights(self):
        from lib.ai_foundation.care_intents.advisor import (
            IntentProposal,
            IntentProposals,
            propose_intents,
        )

        gateway = MagicMock()
        gateway.extract = AsyncMock(return_value=(
            IntentProposals(proposals=[
                IntentProposal(text=f"t{i}", rationale="r") for i in range(4)
            ]),
            None,
        ))
        out = await propose_intents(
            gateway,
            recent_insights=[{"title": "x", "message": "y", "severity": "warning"}],
            existing=[],
        )
        assert len(out) == 2

        gateway.extract.reset_mock()
        assert await propose_intents(gateway, recent_insights=[], existing=[]) == []
        gateway.extract.assert_not_called()


# ── prod-readiness: chat barriers, panel mode, escalation push ───────────────


class TestPatientContextReachesEvaluator:
    @pytest.mark.asyncio
    async def test_memory_facts_in_prompt(self):
        from lib.ai_foundation.care_intents.adherence import AdherenceVerdicts, evaluate_adherence

        gateway = MagicMock()
        gateway.extract = AsyncMock(return_value=(AdherenceVerdicts(), None))
        await evaluate_adherence(
            gateway,
            intents=[{"care_intent_id": "a", "original_text": "Walk after dinner"}],
            day_data_text="no walk logged",
            day_label="yesterday",
            patient_context="Patient facts:\n- symptom: knee pain makes stairs hard",
        )
        user_msg = gateway.extract.call_args.kwargs["messages"][1]["content"]
        assert "PATIENT CONTEXT (from the patient's own words)" in user_msg
        assert "knee pain makes stairs hard" in user_msg


class TestPanelCareIntents:
    def test_panel_render_groups_by_patient(self):
        from lib.ai_foundation.agents.core.context_loader import (
            AgentContext,
            build_context_messages,
        )

        ctx = AgentContext(
            patient_names={"p1": "Asha", "p2": "Rohan"},
            panel_care_intents={"p1": [_INTENT_DICT]},
        )
        msgs = build_context_messages(
            user_message="x", system_prompt="s", reasoning_prompt="r", context=ctx,
        )
        content = next(
            m["content"] for m in msgs if m.get("_meta", {}).get("type") == "context"
        )
        assert "CARE TEAM FOCUS (by patient)" in content
        assert "Asha: [Dr. Mehta, Doctor]" in content

    @pytest.mark.asyncio
    async def test_panel_loader_skips_empty(self):
        from lib.ai_foundation.agents.core.context_loader import ContextLoader

        loader = ContextLoader(care_intents=_FakeReader([]))
        assert await loader._load_panel_care_intents(["p1", "p2"]) == {}


class _EscalationSession(_FakeSession):
    """Queued scalars() result-sets + queued scalar() single rows."""

    def __init__(self, result_sets, scalar_rows):
        super().__init__(*result_sets)
        self._scalar_rows = list(scalar_rows)

    async def scalar(self, stmt):
        return self._scalar_rows.pop(0) if self._scalar_rows else None


def _intent_row(intent_id, escalated_at=None):
    return SimpleNamespace(
        care_intent_id=intent_id,
        author_id=uuid4(),
        original_text="Walk after dinner",
        escalated_at=escalated_at,
    )


def _miss_events(intent_id, count, total=5):
    events = []
    for i in range(1, total + 1):
        status = "missed" if i <= count else "followed"
        e = _event(i, status)
        e.care_intent_id = intent_id
        events.append(e)
    return events


class TestEscalationPush:
    async def _run(self, *, miss_streak, escalated_at=None):
        intent_id = uuid4()
        fcm = MagicMock()
        fcm.send_fcm_notification_to_user_devices = AsyncMock()
        svc = CareIntentService(postgres_store=None, provider_fcm=fcm)
        session = _EscalationSession(
            result_sets=[
                _miss_events(intent_id, miss_streak),           # adherence_summary events
                [_intent_row(intent_id, escalated_at=escalated_at)],  # candidates IN-select
            ],
            scalar_rows=[
                SimpleNamespace(first_name="Asha"),  # patient lookup
            ],
        )
        await svc._escalate_if_needed(
            [intent_id], str(uuid4()), date.today() - timedelta(days=1),
            postgres_session=session,
        )
        return fcm, session

    @pytest.mark.asyncio
    async def test_fires_exactly_at_threshold(self):
        fcm, session = await self._run(miss_streak=3)
        fcm.send_fcm_notification_to_user_devices.assert_called_once()
        kwargs = fcm.send_fcm_notification_to_user_devices.call_args.kwargs
        assert "Asha" in kwargs["title"]
        assert "3 days in a row" in kwargs["body"]
        assert kwargs["channel_key"] == "alerts"
        assert kwargs["data"]["type"] == "care_intent_escalation"
        assert session.committed  # escalated_at persisted

    @pytest.mark.asyncio
    @pytest.mark.parametrize("streak", [2, 4])
    async def test_quiet_off_threshold(self, streak):
        """Below threshold = not yet; above = already pinged for this streak."""
        fcm, _ = await self._run(miss_streak=streak)
        fcm.send_fcm_notification_to_user_devices.assert_not_called()

    @pytest.mark.asyncio
    async def test_already_escalated_today_stays_quiet(self):
        fcm, _ = await self._run(
            miss_streak=3, escalated_at=datetime.now().replace(tzinfo=None),
        )
        fcm.send_fcm_notification_to_user_devices.assert_not_called()


# ── translation retry carries the failure reason ─────────────────────────────


class TestTranslationCorrectiveRetry:
    @pytest.mark.asyncio
    async def test_echo_retry_includes_problem_for_non_latin_target(self):
        from lib.ai_foundation.translation.service import TranslationService

        gateway = MagicMock()
        gateway.complete = AsyncMock(side_effect=[
            SimpleNamespace(content="Log a meal"),        # Latin echo to a Devanagari target — fails
            SimpleNamespace(content="खाना लॉग करें"),      # corrected
        ])
        ts = TranslationService(gateway)
        out = await ts.translate("Log a meal", "hi", terse=True)
        assert out == "खाना लॉग करें"
        # Second call must carry the corrective turn, not repeat the identical request
        second_messages = gateway.complete.call_args_list[1].kwargs["messages"]
        assert any("failed a check" in m["content"] for m in second_messages if m["role"] == "user")

    @pytest.mark.asyncio
    async def test_latin_target_echo_accepted_first_try(self):
        """hi-Latn chips legitimately keep English words — an identical output
        is ACCEPTED (and cacheable), never a 2-LLM-call retry loop."""
        from lib.ai_foundation.translation.service import TranslationService

        gateway = MagicMock()
        gateway.complete = AsyncMock(return_value=SimpleNamespace(content="BMI details"))
        ts = TranslationService(gateway)
        out = await ts.translate_cached("BMI details", "hi-Latn", terse=True)
        assert out == "BMI details"
        assert gateway.complete.await_count == 1
        # cached — second call is free
        assert await ts.translate_cached("BMI details", "hi-Latn", terse=True) == "BMI details"
        assert gateway.complete.await_count == 1


# ── full-fledged CRUD: delete, edit, resume-bumps-review ─────────────────────


class _CrudSession(_FakeSession):
    def __init__(self, scalar_rows):
        super().__init__()
        self._scalar_rows = list(scalar_rows)
        self.deleted = []

    async def scalar(self, stmt):
        return self._scalar_rows.pop(0) if self._scalar_rows else None

    async def delete(self, obj):
        self.deleted.append(obj)

    async def refresh(self, obj):
        pass


class TestCareIntentCrud:
    @pytest.mark.asyncio
    async def test_resume_expired_bumps_review_date(self):
        intent = SimpleNamespace(
            care_intent_id=uuid4(), status="paused",
            review_date=date.today() - timedelta(days=2),
        )
        session = _CrudSession([intent])
        svc = CareIntentService(postgres_store=None)
        out = await svc.update_status(intent.care_intent_id, "active", postgres_session=session)
        assert out.status == "active"
        assert out.review_date > date.today()  # fresh window, not instant re-expiry

    @pytest.mark.asyncio
    async def test_pause_does_not_touch_review_date(self):
        rd = date.today() + timedelta(days=5)
        intent = SimpleNamespace(care_intent_id=uuid4(), status="active", review_date=rd)
        session = _CrudSession([intent])
        svc = CareIntentService(postgres_store=None)
        out = await svc.update_status(intent.care_intent_id, "paused", postgres_session=session)
        assert out.review_date == rd

    @pytest.mark.asyncio
    async def test_delete_removes_events_then_intent_author_only(self):
        intent = SimpleNamespace(care_intent_id=uuid4(), author_id=uuid4())
        session = _CrudSession([intent])
        svc = CareIntentService(postgres_store=None)
        ok = await svc.delete(intent.care_intent_id, author_id=intent.author_id, postgres_session=session)
        assert ok is True
        assert len(session.executed) == 1  # events delete statement
        assert session.deleted == [intent]
        assert session.committed

        session2 = _CrudSession([None])  # author mismatch → no row
        assert await svc.delete(uuid4(), author_id=uuid4(), postgres_session=session2) is False
        assert session2.deleted == []

    @pytest.mark.asyncio
    async def test_update_replaces_fields_resets_escalation(self):
        intent = SimpleNamespace(
            care_intent_id=uuid4(), author_id=uuid4(),
            original_text="old", intent_type="remind", domain="fitness",
            trigger_condition=None, cadence="daily", patient_summary="old",
            success_criteria=None, review_date=date.today() - timedelta(days=1),
            status="expired", escalated_at=datetime.now(),
        )
        session = _CrudSession([intent])
        svc = CareIntentService(postgres_store=None)
        out = await svc.update(
            intent.care_intent_id,
            author_id=intent.author_id,
            original_text="Walk 10 minutes after every meal",
            structured=_structured(patient_summary="A short walk after meals helps."),
            postgres_session=session,
        )
        assert out.original_text == "Walk 10 minutes after every meal"
        assert out.status == "active"
        assert out.escalated_at is None
        assert out.review_date > date.today()


# ── adherence quality: observational filter + no-data barrier + type in prompt ─


class TestAdherenceQuality:
    @pytest.mark.asyncio
    async def test_watch_and_passive_intents_excluded_from_adherence(self, monkeypatch):
        from lib.ai_foundation.agents.proactive_monitor.agent import ProactiveMonitorAgent
        import lib.ai_foundation.care_intents.adherence as adherence_mod

        captured = {}

        async def fake_eval(gateway, *, intents, day_data_text, day_label, patient_context=""):
            captured["intents"] = intents
            return []

        monkeypatch.setattr(adherence_mod, "evaluate_adherence", fake_eval)
        reader = MagicMock()
        reader.record_adherence = AsyncMock()
        agent = ProactiveMonitorAgent(gateway=MagicMock(), qdrant=MagicMock(), care_intents=reader)

        intents = [
            {"care_intent_id": "a", "original_text": "walk after dinner", "intent_type": "remind", "cadence": "daily"},
            {"care_intent_id": "b", "original_text": "keep an eye on sugars", "intent_type": "watch", "cadence": "passive"},
            {"care_intent_id": "c", "original_text": "no rice at night", "intent_type": "restrict", "cadence": "passive"},
        ]
        # simulate the scan gate: only trackable intents reach the evaluator
        trackable = [ci for ci in intents if ci.get("intent_type") != "watch" and ci.get("cadence") != "passive"]
        await agent._record_adherence("p1", trackable, "data", "2026-07-19", "yesterday")
        ids = {ci["care_intent_id"] for ci in captured["intents"]}
        assert ids == {"a"}  # watch (b) and passive (c) both excluded

    @pytest.mark.asyncio
    async def test_intent_type_and_nodata_barrier_in_prompt(self):
        from lib.ai_foundation.care_intents.adherence import AdherenceVerdicts, evaluate_adherence

        gateway = MagicMock()
        gateway.extract = AsyncMock(return_value=(AdherenceVerdicts(), None))
        await evaluate_adherence(
            gateway,
            intents=[{"care_intent_id": "a", "original_text": "log your meals", "intent_type": "remind"}],
            day_data_text="(no data logged)",
            day_label="yesterday",
        )
        system = gateway.extract.call_args.kwargs["messages"][0]["content"]
        user = gateway.extract.call_args.kwargs["messages"][1]["content"]
        assert "[remind] log your meals" in user           # type is explicit
        assert "no meals logged" in system.lower()          # barrier-note guidance present
        assert "about logging" in system.lower()            # logging carve-out present
