from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.gamification.helpers import FakeScalarResult, FakeSession, load_module


class TestCPGamificationService:
    @pytest.mark.asyncio
    async def test_get_overview_counts_and_sorts_at_risk_patients(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/care_provider_service.py",
            "gamification_test_cp_service_overview",
        )

        class FakeDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 4, 3)

        monkeypatch.setattr(module, "date", FakeDate)
        service = module.CPGamificationService(postgres_store=None)
        patient_active = uuid4()
        patient_risk = uuid4()
        session = FakeSession(
            results=[
                FakeScalarResult(values=[patient_active, patient_risk]),
                FakeScalarResult(
                    values=[
                        SimpleNamespace(
                            patient_id=patient_active,
                            level=8,
                            current_streak=5,
                            total_xp=1500,
                            last_active_date=date(2026, 4, 2),
                        ),
                        SimpleNamespace(
                            patient_id=patient_risk,
                            level=3,
                            current_streak=0,
                            total_xp=120,
                            last_active_date=date(2026, 3, 20),
                        ),
                    ]
                ),
                FakeScalarResult(
                    values=[
                        SimpleNamespace(patient_id=patient_active, first_name="Active"),
                        SimpleNamespace(patient_id=patient_risk, first_name="Risky"),
                    ]
                ),
                FakeScalarResult(
                    values=[
                        SimpleNamespace(patient_id=patient_active, cnt=4),
                        SimpleNamespace(patient_id=patient_risk, cnt=1),
                    ]
                ),
            ]
        )

        overview = await service.get_overview(uuid4(), postgres_session=session)

        assert overview.total_patients == 2
        assert overview.active_patients == 1
        assert overview.at_risk_patients == 1
        assert [patient.patient_name for patient in overview.patients] == [
            "Risky",
            "Active",
        ]

    @pytest.mark.asyncio
    async def test_star_achievement_sets_star_fields(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/care_provider_service.py",
            "gamification_test_cp_service_star",
        )
        service = module.CPGamificationService(postgres_store=None)
        pa = SimpleNamespace(starred_by=None, starred_at=None)
        cp_id = uuid4()
        session = FakeSession(results=[FakeScalarResult(values=[pa])])

        await service.star_achievement(
            care_provider_id=cp_id,
            patient_achievement_id=uuid4(),
            postgres_session=session,
        )

        assert pa.starred_by == cp_id
        assert pa.starred_at is not None
        assert session.commit_count == 1

    @pytest.mark.asyncio
    async def test_get_groups_returns_group_responses_with_member_counts(self, monkeypatch):
        module = load_module(
            monkeypatch,
            "lib/services/gamification/care_provider_service.py",
            "gamification_test_cp_service_groups",
        )
        service = module.CPGamificationService(postgres_store=None)
        group = SimpleNamespace(
            group_id=uuid4(),
            name="Dr. A Team",
            description="Care provider group",
            group_type="care_provider",
            created_by_id=uuid4(),
            created_by_type="care_provider",
            facility_id=None,
            max_members=50,
            is_active=True,
            created_at=date(2026, 4, 3),
            invite_code="ABC123",
            avatar_url=None,
        )
        session = FakeSession(
            results=[
                FakeScalarResult(values=[group]),
                FakeScalarResult(scalar=7),
            ]
        )

        groups = await service.get_groups(uuid4(), postgres_session=session)

        assert len(groups) == 1
        assert groups[0].name == "Dr. A Team"
        assert groups[0].member_count == 7
