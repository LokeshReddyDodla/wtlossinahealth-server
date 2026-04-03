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
        session = FakeSession(
            results=[
                FakeScalarResult(values=[SimpleNamespace(ChallengeParticipant=patient_participant, Challenge=challenge)]),
                FakeScalarResult(values=[group_id]),
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

        monkeypatch.setattr(service, "_patient_today", fake_patient_today)
        monkeypatch.setattr(service, "_participant_count", fake_participant_count)
        monkeypatch.setattr(service, "_to_response", lambda challenge, count: (challenge.challenge_id, count))

        session = FakeSession(
            results=[
                FakeScalarResult(values=[group_id]),
                FakeScalarResult(values=[shared_challenge]),
                FakeScalarResult(values=[shared_challenge]),
            ]
        )

        active = await service.get_active_challenges(
            patient_id=patient_id,
            postgres_session=session,
        )

        assert active == [(shared_challenge.challenge_id, 3)]
