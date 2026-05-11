from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module


class TestChallengeService:
    @pytest.mark.asyncio
    async def test_update_participant_progress_marks_completion_and_commits(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            "gamification_test_challenge_service_progress",
        )
        service = module.ChallengeService(postgres_store=None, xp_service=None)
        patient_id = uuid4()
        group_id = uuid4()

        patient_participant = SimpleNamespace(
            participant_type="patient",
            participant_id=patient_id,
            current_value=4.0,
            status="active",
            completed_at=None,
        )
        group_participant = SimpleNamespace(
            participant_type="group",
            participant_id=group_id,
            current_value=9.0,
            status="active",
            completed_at=None,
        )
        challenge = SimpleNamespace(target_value=10.0)

        async def fake_patient_today(_patient_id, _session):
            return date(2026, 4, 3)

        monkeypatch.setattr(service, "_patient_today", fake_patient_today)

        async def fake_active_group_ids(_pid, _session):
            return [group_id]

        monkeypatch.setattr(module, "active_group_ids", fake_active_group_ids)
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(ChallengeParticipant=patient_participant, Challenge=challenge)]),
                FakeScalarResult(values=[SimpleNamespace(ChallengeParticipant=group_participant, Challenge=challenge)]),
            ]
        )

        await service.update_participant_progress(
            patient_id=patient_id,
            metric_type="steps",
            increment=1.0,
            postgres_session=session,
        )

        assert patient_participant.current_value == 5.0
        assert patient_participant.status == "active"
        assert group_participant.current_value == 10.0
        assert group_participant.status == "completed"
        assert group_participant.completed_at is not None
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_get_finalizable_challenge_ids_requires_all_timezones_past_end(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            "gamification_test_challenge_service_finalizable",
        )
        service = module.ChallengeService(postgres_store=None, xp_service=None)

        challenge_done = SimpleNamespace(challenge_id=uuid4(), end_date=date(2026, 4, 2))
        challenge_open = SimpleNamespace(challenge_id=uuid4(), end_date=date(2026, 4, 3))

        async def fake_challenge_patient_ids(challenge_id, _session):
            if challenge_id == challenge_done.challenge_id:
                return [uuid4()]
            return [uuid4()]

        monkeypatch.setattr(service, "_challenge_patient_ids", fake_challenge_patient_ids)
        monkeypatch.setattr(
            module,
            "local_today",
            lambda tz_name=None: date(2026, 4, 4) if tz_name == "Asia/Kolkata" else date(2026, 4, 3),
        )

        session = FakeSession(
            results=[
                FakeScalarResult(values=[challenge_done, challenge_open]),
                FakeScalarResult(values=["Asia/Kolkata"]),
                FakeScalarResult(values=["America/New_York"]),
            ]
        )

        finalizable = await service.get_finalizable_challenge_ids(
            postgres_session=session,
        )

        assert finalizable == [challenge_done.challenge_id]

    @pytest.mark.asyncio
    async def test_get_active_challenges_deduplicates_patient_and_group_entries(
        self,
        monkeypatch,
    ):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            "gamification_test_challenge_service_active",
        )
        service = module.ChallengeService(postgres_store=None, xp_service=None)
        patient_id = uuid4()
        group_id = uuid4()
        shared_challenge = SimpleNamespace(challenge_id=uuid4())

        async def fake_patient_today(_patient_id, _session):
            return date(2026, 4, 3)

        async def fake_participant_count(_challenge_id, _session):
            return 3

        async def fake_active_group_ids(_pid, _session):
            return [group_id]

        monkeypatch.setattr(service, "_patient_today", fake_patient_today)
        monkeypatch.setattr(service, "_participant_count", fake_participant_count)
        monkeypatch.setattr(service, "_to_response", lambda challenge, count: (challenge.challenge_id, count))
        monkeypatch.setattr(module, "active_group_ids", fake_active_group_ids)

        session = FakeSession(
            results=[
                FakeScalarResult(values=[shared_challenge]),
                FakeScalarResult(values=[shared_challenge]),
            ]
        )

        active = await service.get_active_challenges(
            patient_id=patient_id,
            postgres_session=session,
        )

        assert active == [(shared_challenge.challenge_id, 3)]


class TestParticipantRewardPolicy:
    """Locks the XP-reward policy for `_participant_reward_xp`.

    Salvaged from the now-deleted tests/test_gamification_unit_logic.py.
    """

    def _service(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            f"challenge_reward_policy_{uuid4().hex}",
        )
        return object.__new__(module.ChallengeService)

    def test_group_competitive_winner_gets_base_plus_bonus(self, monkeypatch):
        service = self._service(monkeypatch)
        challenge = SimpleNamespace(
            scope="group_competitive", xp_reward=50, bonus_xp_winner=25,
        )
        participant = SimpleNamespace(
            participant_type="group", status="active", rank=1,
        )
        assert service._participant_reward_xp(challenge, participant) == 75

    def test_cooperative_requires_completion(self, monkeypatch):
        service = self._service(monkeypatch)
        challenge = SimpleNamespace(
            scope="group_cooperative", xp_reward=80, bonus_xp_winner=0,
        )
        incomplete = SimpleNamespace(
            participant_type="group", status="active", rank=2,
        )
        complete = SimpleNamespace(
            participant_type="group", status="completed", rank=2,
        )
        assert service._participant_reward_xp(challenge, incomplete) == 0
        assert service._participant_reward_xp(challenge, complete) == 80


class TestChallengeUpdateAndCancel:
    @pytest.mark.asyncio
    async def test_update_challenge_changes_title_and_target(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            "challenge_update_basic",
        )
        service = object.__new__(module.ChallengeService)
        challenge = SimpleNamespace(
            challenge_id=uuid4(),
            is_active=True,
            title="Old",
            description=None,
            target_value=100.0,
            xp_reward=50,
            bonus_xp_winner=0,
        )

        async def fake_get_challenge(_cid, _s):
            return challenge

        async def fake_participant_count(_cid, _s):
            return 3

        monkeypatch.setattr(service, "_get_challenge", fake_get_challenge)
        monkeypatch.setattr(service, "_participant_count", fake_participant_count)

        # Stub _to_response — staticmethod, doesn't need self
        monkeypatch.setattr(
            module.ChallengeService,
            "_to_response",
            staticmethod(
                lambda c, count: SimpleNamespace(
                    challenge_id=str(c.challenge_id),
                    title=c.title,
                    target_value=c.target_value,
                    participant_count=count,
                )
            ),
        )

        result = await service.update_challenge(
            challenge.challenge_id,
            title="New title",
            target_value=200.0,
            postgres_session=FakeSession(),
        )

        assert challenge.title == "New title"
        assert challenge.target_value == 200.0
        assert result.title == "New title"
        assert result.participant_count == 3

    @pytest.mark.asyncio
    async def test_update_challenge_rejects_inactive(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            "challenge_update_inactive",
        )
        service = object.__new__(module.ChallengeService)
        challenge = SimpleNamespace(challenge_id=uuid4(), is_active=False)

        async def fake_get(_c, _s):
            return challenge

        monkeypatch.setattr(service, "_get_challenge", fake_get)

        with pytest.raises(ValueError, match="Cannot edit an inactive challenge"):
            await service.update_challenge(
                challenge.challenge_id, title="X", postgres_session=FakeSession(),
            )

    @pytest.mark.asyncio
    async def test_update_challenge_raises_when_not_found(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            "challenge_update_missing",
        )
        service = object.__new__(module.ChallengeService)

        async def fake_get(_c, _s):
            return None

        monkeypatch.setattr(service, "_get_challenge", fake_get)

        with pytest.raises(ValueError, match="Challenge not found"):
            await service.update_challenge(uuid4(), title="X", postgres_session=FakeSession())

    @pytest.mark.asyncio
    async def test_cancel_challenge_marks_inactive_and_withdraws_active_participants(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            "challenge_cancel",
        )
        service = object.__new__(module.ChallengeService)
        challenge = SimpleNamespace(challenge_id=uuid4(), is_active=True)
        participants = [
            SimpleNamespace(status="active"),
            SimpleNamespace(status="active"),
        ]

        async def fake_get(_c, _s):
            return challenge

        monkeypatch.setattr(service, "_get_challenge", fake_get)
        session = FakeSession(results=[FakeScalarResult(values=participants)])

        await service.cancel_challenge(challenge.challenge_id, postgres_session=session)

        assert challenge.is_active is False
        assert all(p.status == "withdrawn" for p in participants)
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_cancel_challenge_is_noop_on_already_inactive(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/challenge_service.py",
            "challenge_cancel_noop",
        )
        service = object.__new__(module.ChallengeService)
        challenge = SimpleNamespace(challenge_id=uuid4(), is_active=False)

        async def fake_get(_c, _s):
            return challenge

        monkeypatch.setattr(service, "_get_challenge", fake_get)
        session = FakeSession()

        await service.cancel_challenge(challenge.challenge_id, postgres_session=session)
        assert session.commit_count == 0
