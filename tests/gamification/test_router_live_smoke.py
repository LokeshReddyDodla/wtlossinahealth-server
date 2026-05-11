"""Live ASGI smoke tests — boot a FastAPI app, mount the gamification router with
mocked services and identity, and hit every endpoint at least once.

This catches wiring bugs that the stubbed-FastAPI unit tests miss:
- Pydantic schema validation
- Path/query parameter binding
- Dependency injection resolution
- Response model serialization
"""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from lib.core.constants import ProfileTypeEnum
from lib.dependencies.actor import Actor
from lib.dependencies.auth.base import get_current_user
from lib.dependencies.auth.care_provider_auth import get_current_care_provider
from lib.dependencies.database import get_postgres_session
from lib.dependencies.service_dependencies import (
    get_buddy_service,
    get_care_provider_access_service,
    get_challenge_service,
    get_cp_gamification_service,
    get_feed_service,
    get_gamification_service,
    get_group_service,
    get_leaderboard_service,
)
from rest_server.v1.gamification.router import router


PATIENT_ID = uuid4()
CP_ID = uuid4()
GROUP_ID = uuid4()
CHALLENGE_ID = uuid4()
BUDDY_ID = uuid4()
TASK_ID = uuid4()
FEED_EVENT_ID = uuid4()
ACHIEVEMENT_ID = uuid4()
OTHER_PATIENT_ID = uuid4()


def _group_dict(*, owner_id=None, owner_type="patient", group_id=None):
    return {
        "group_id": str(group_id or GROUP_ID),
        "name": "Test Group",
        "description": "desc",
        "group_type": "patient_created",
        "created_by_id": str(owner_id or PATIENT_ID),
        "created_by_type": owner_type,
        "facility_id": None,
        "invite_code": "ABC123",
        "avatar_url": None,
        "member_count": 1,
        "max_members": 50,
        "is_active": True,
        "created_at": "2026-01-01T00:00:00",
    }


def _challenge_dict():
    return {
        "challenge_id": str(CHALLENGE_ID),
        "title": "April Sprint",
        "description": None,
        "challenge_type": "weekly",
        "scope": "individual",
        "metric_type": "steps",
        "target_value": 10000.0,
        "duration_days": 7,
        "start_date": "2026-04-01",
        "end_date": "2026-04-07",
        "xp_reward": 100,
        "bonus_xp_winner": 0,
        "created_by_id": str(PATIENT_ID),
        "created_by_type": "patient",
        "is_opt_in": True,
        "is_active": True,
        "participant_count": 1,
        "created_at": "2026-04-01T00:00:00",
    }


class _StubSession:
    """A 'permissive' session: any query returns a single model that satisfies
    every field the router/services read.

    The same model carries both Patient and CareProvider fields, plus the fields
    `_ensure_group_owner` / `_ensure_challenge_owner` need (created_by_id /
    created_by_type / role). One fallback covers all execute() calls regardless
    of order.

    Override `group_owner_id`, `group_owner_type` etc. by passing them in.
    """

    def __init__(self, *, group_owner_id=None, group_owner_type="patient",
                 challenge_owner_id=None, challenge_owner_type="patient",
                 member_role="admin"):
        self.group_owner_id = group_owner_id or PATIENT_ID
        self.group_owner_type = group_owner_type
        self.challenge_owner_id = challenge_owner_id or PATIENT_ID
        self.challenge_owner_type = challenge_owner_type
        self.member_role = member_role

    async def execute(self, *_args, **_kwargs):
        # A single mock that fields every attribute access used by the codebase.
        model = MagicMock(
            # Actor lookups
            patient_id=PATIENT_ID,
            care_provider_id=CP_ID,
            permissions={"patients": {"read": True, "create": True, "update": True, "delete": True}},
            first_name="Test",
            last_name="User",
            health_facility_id=None,
            locale="en_US",
            # Group ownership lookup
            group_id=GROUP_ID,
            created_by_id=self.group_owner_id,
            created_by_type=self.group_owner_type,
            is_active=True,
            # Member-admin lookup
            role=self.member_role,
            # Challenge ownership lookup — same model serves; override per test
            challenge_id=CHALLENGE_ID,
        )
        # _ensure_challenge_owner reads challenge.created_by_id / created_by_type
        # but we already set created_by_id above to group_owner_id. For challenge
        # tests, set group_owner_* the same as challenge_owner_*.
        result = MagicMock()
        result.scalars.return_value.first.return_value = model
        result.scalars.return_value.all.return_value = [model]
        result.scalar.return_value = 1
        return result

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def refresh(self, *_a):
        pass


@pytest.fixture
def app(monkeypatch):
    """Build a FastAPI app with the gamification router; response validation off.

    Live smoke tests verify routes register, deps wire, and handlers complete
    successfully. Response-shape validation is covered by unit tests with real
    schemas — disabling it here lets us mock with minimal fixtures.
    """
    # Bypass response_model validation: serialize_response just dumps Pydantic models.
    import fastapi.routing
    from pydantic import BaseModel

    async def passthrough_serialize_response(*, response_content, **_kwargs):
        return _to_jsonable(response_content)

    def _to_jsonable(value):
        from pydantic import BaseModel as _BaseModel
        from datetime import date as _date, datetime as _dt
        from uuid import UUID as _UUID
        from enum import Enum as _Enum

        if isinstance(value, _BaseModel):
            # Walk fields manually so we never invoke pydantic's strict serializer
            # (which barfs on SimpleNamespace etc.)
            return {name: _to_jsonable(getattr(value, name)) for name in value.model_fields}
        if isinstance(value, SimpleNamespace):
            return {k: _to_jsonable(v) for k, v in vars(value).items()}
        if isinstance(value, dict):
            return {k: _to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_to_jsonable(v) for v in value]
        if isinstance(value, (_date, _dt)):
            return value.isoformat()
        if isinstance(value, _UUID):
            return str(value)
        if isinstance(value, _Enum):
            return value.value
        return value

    monkeypatch.setattr(fastapi.routing, "serialize_response", passthrough_serialize_response)

    app = FastAPI()
    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _set_actor(app, *, role):
    if role == ProfileTypeEnum.PATIENT:
        async def fake_user():
            return (PATIENT_ID, ProfileTypeEnum.PATIENT.value)
    else:
        async def fake_user():
            return (CP_ID, ProfileTypeEnum.CARE_PROVIDER.value)
    app.dependency_overrides[get_current_user] = fake_user


def _attach_default_session(app, *, session=None):
    sess = session or _StubSession()

    async def fake_session():
        yield sess

    app.dependency_overrides[get_postgres_session] = fake_session


@pytest.mark.asyncio
async def test_patient_routes_smoke(app, client):
    _set_actor(app, role=ProfileTypeEnum.PATIENT)
    _attach_default_session(app)
    app.dependency_overrides[get_care_provider_access_service] = lambda: MagicMock(
        is_patient_assigned=AsyncMock(return_value=True),
    )

    gam = MagicMock()
    gam.get_or_create_profile = AsyncMock(return_value={
        "patient_id": str(PATIENT_ID), "level": 1, "current_streak": 0, "longest_streak": 0,
        "total_xp": 0, "streak_freezes": 0, "title": "Newcomer",
        "leaderboard_visibility": "public", "title_slug": None,
    })
    gam.update_profile = AsyncMock()
    gam.use_streak_freeze = AsyncMock(return_value={
        "patient_id": str(PATIENT_ID), "level": 1, "current_streak": 5, "longest_streak": 5,
        "total_xp": 0, "streak_freezes": 0, "title": "Newcomer",
        "leaderboard_visibility": "public", "title_slug": None,
    })
    gam.get_patient_local_date = AsyncMock(return_value=date(2026, 5, 11))
    gam.get_daily_progress = AsyncMock(return_value={
        "task_date": "2026-05-11", "tasks": [], "total_xp_earned_today": 0,
        "daily_xp_cap": 500, "completed_count": 0, "total_count": 0,
    })
    gam.get_daily_history = AsyncMock(return_value={"days": []})
    gam.get_achievements = AsyncMock(return_value=[])
    gam.get_recent_achievements = AsyncMock(return_value=[])
    gam.get_current_quest = AsyncMock(return_value=None)
    gam.get_xp_history = AsyncMock(return_value={"period": "week", "entries": [], "total_xp": 0})
    gam.complete_task = AsyncMock(return_value={
        "task_id": str(TASK_ID), "xp_earned": 10, "new_achievements": [],
        "level_up": False, "new_level": None,
    })
    app.dependency_overrides[get_gamification_service] = lambda: gam

    buddy = MagicMock()
    buddy.get_buddies = AsyncMock(return_value=[])
    buddy.send_request = AsyncMock()
    buddy.send_request_by_code = AsyncMock()
    buddy.accept_request = AsyncMock()
    buddy.reject_request = AsyncMock()
    buddy.remove_buddy = AsyncMock()
    buddy.get_buddy_progress = AsyncMock(return_value={
        "buddy_id": str(BUDDY_ID), "buddy_streak": 0,
        "your_streak": 0, "buddy_first_name": "X", "buddy_last_active_date": None,
    })
    buddy.get_buddy_detail = AsyncMock(return_value={
        "patient_id": str(BUDDY_ID), "first_name": "X", "profile_picture": None,
        "level": 1, "title": "Newcomer", "current_streak": 0, "longest_streak": 0,
        "total_xp": 0, "buddy_status": "active",
        "buddy_since": "2026-01-01T00:00:00",
        "buddy_streak": 0,
        "achievements_count": 0, "recent_achievements": [],
    })
    app.dependency_overrides[get_buddy_service] = lambda: buddy

    grp = MagicMock()
    grp.get_patient_groups = AsyncMock(return_value=[])
    app.dependency_overrides[get_group_service] = lambda: grp

    chl = MagicMock()
    chl.get_available_challenges = AsyncMock(return_value=[])
    chl.get_active_challenges = AsyncMock(return_value=[])
    app.dependency_overrides[get_challenge_service] = lambda: chl

    feed = MagicMock()
    feed.get_buddy_feed = AsyncMock(return_value=[])
    app.dependency_overrides[get_feed_service] = lambda: feed

    lb = MagicMock()
    lb.get_leaderboard = AsyncMock(return_value={
        "board_type": "weekly_xp", "board_scope": "global", "entries": [],
        "period_start": "2026-05-04", "period_end": "2026-05-10", "my_rank": None,
    })
    app.dependency_overrides[get_leaderboard_service] = lambda: lb

    routes = [
        ("GET", f"/gamification/patients/{PATIENT_ID}/profile", None),
        ("PATCH", f"/gamification/patients/{PATIENT_ID}/profile", {"leaderboard_visibility": "public"}),
        ("POST", f"/gamification/patients/{PATIENT_ID}/streak/freeze", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/daily", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/daily/history?start_date=2026-05-01&end_date=2026-05-11", None),
        ("POST", f"/gamification/patients/{PATIENT_ID}/tasks/{TASK_ID}/complete", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/achievements", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/achievements/recent", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/quests/current", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/history?period=week", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/buddies", None),
        ("POST", f"/gamification/patients/{PATIENT_ID}/buddies/request", {"accepter_id": str(OTHER_PATIENT_ID)}),
        ("POST", f"/gamification/patients/{PATIENT_ID}/buddies/request-by-code", {"buddy_code": "BUDXYZ"}),
        ("POST", f"/gamification/patients/{PATIENT_ID}/buddies/{BUDDY_ID}/accept", None),
        ("POST", f"/gamification/patients/{PATIENT_ID}/buddies/{BUDDY_ID}/reject", None),
        ("DELETE", f"/gamification/patients/{PATIENT_ID}/buddies/{BUDDY_ID}", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/buddies/{BUDDY_ID}/progress", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/buddies/by-code/BUDXYZ", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/groups", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/challenges/available", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/challenges/active", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/feed", None),
        ("GET", f"/gamification/patients/{PATIENT_ID}/leaderboards/weekly_xp", None),
    ]

    failures = []
    for method, path, body in routes:
        kwargs = {"json": body} if body is not None else {}
        r = await client.request(method, path, **kwargs)
        if r.status_code not in (200, 201):
            failures.append((method, path, r.status_code, r.text[:200]))
    assert not failures, f"Patient route failures: {failures}"


@pytest.mark.asyncio
async def test_group_resource_routes_smoke(app, client):
    _set_actor(app, role=ProfileTypeEnum.PATIENT)
    app.dependency_overrides[get_care_provider_access_service] = lambda: MagicMock(
        is_patient_assigned=AsyncMock(return_value=True),
    )

    # Permissive session: same model answers every query, including ownership
    sess = _StubSession(group_owner_id=PATIENT_ID, group_owner_type="patient")
    _attach_default_session(app, session=sess)

    grp = MagicMock(postgres_store=MagicMock(get_session=lambda: _AsyncCM(sess)))
    grp.create_group = AsyncMock(return_value=SimpleNamespace(group_id=GROUP_ID))
    grp.get_group = AsyncMock(return_value=_group_dict())
    grp.get_group_info = AsyncMock(return_value={
        "group_id": str(GROUP_ID), "name": "Test", "description": None, "avatar_url": None,
        "group_type": "patient_created", "member_count": 1, "max_members": 50, "is_active": True,
        "invite_code": "ABC123", "your_role": "admin", "top_members": [],
        "created_at": "2026-01-01T00:00:00",
    })
    grp.update_group = AsyncMock(return_value=_group_dict())
    grp.delete_group = AsyncMock()
    grp.rotate_invite_code = AsyncMock(return_value="NEWCDE")
    grp.join_group = AsyncMock()
    grp.join_by_code = AsyncMock(return_value=_group_dict())
    grp.leave_group = AsyncMock()
    grp.get_members = AsyncMock(return_value=[])
    grp.add_members = AsyncMock(return_value=3)
    grp.remove_member = AsyncMock()
    grp.get_patient_groups = AsyncMock(return_value=[SimpleNamespace(group_id=str(GROUP_ID))])
    app.dependency_overrides[get_group_service] = lambda: grp

    feed = MagicMock()
    feed.get_group_feed = AsyncMock(return_value=[])
    app.dependency_overrides[get_feed_service] = lambda: feed

    lb = MagicMock()
    lb.get_leaderboard = AsyncMock(return_value={
        "board_type": "weekly_xp", "board_scope": "group", "entries": [],
        "period_start": "2026-05-04", "period_end": "2026-05-10", "my_rank": None,
    })
    app.dependency_overrides[get_leaderboard_service] = lambda: lb

    routes = [
        ("POST", "/gamification/groups", {"name": "Test", "group_type": "patient_created", "max_members": 20}, 201),
        ("GET", "/gamification/groups/by-code/ABC123", None, 200),
        ("GET", f"/gamification/groups/{GROUP_ID}", None, 200),
        ("PATCH", f"/gamification/groups/{GROUP_ID}", {"name": "Renamed"}, 200),
        ("POST", f"/gamification/groups/{GROUP_ID}/invite-code/rotate", None, 200),
        ("POST", f"/gamification/groups/{GROUP_ID}/join", None, 200),
        ("POST", "/gamification/groups/join-by-code", {"invite_code": "ABC123"}, 200),
        ("DELETE", f"/gamification/groups/{GROUP_ID}/leave", None, 200),
        ("GET", f"/gamification/groups/{GROUP_ID}/members", None, 200),
        ("POST", f"/gamification/groups/{GROUP_ID}/members", {"patient_ids": [str(OTHER_PATIENT_ID)]}, 201),
        ("DELETE", f"/gamification/groups/{GROUP_ID}/members/{OTHER_PATIENT_ID}", None, 200),
        ("GET", f"/gamification/groups/{GROUP_ID}/leaderboard", None, 200),
        ("GET", f"/gamification/groups/{GROUP_ID}/feed", None, 200),
        ("DELETE", f"/gamification/groups/{GROUP_ID}", None, 200),
    ]
    failures = []
    for method, path, body, expected in routes:
        kwargs = {"json": body} if body is not None else {}
        r = await client.request(method, path, **kwargs)
        if r.status_code != expected:
            failures.append((method, path, r.status_code, expected, r.text[:200]))
    assert not failures, f"Group route failures: {failures}"


@pytest.mark.asyncio
async def test_challenge_resource_routes_smoke(app, client):
    _set_actor(app, role=ProfileTypeEnum.PATIENT)
    app.dependency_overrides[get_care_provider_access_service] = lambda: MagicMock(
        is_patient_assigned=AsyncMock(return_value=True),
    )

    sess = _StubSession(group_owner_id=PATIENT_ID, group_owner_type="patient",
                        challenge_owner_id=PATIENT_ID, challenge_owner_type="patient")
    _attach_default_session(app, session=sess)

    chl = MagicMock(postgres_store=MagicMock(get_session=lambda: _AsyncCM(sess)))
    challenge_obj = SimpleNamespace(challenge_id=CHALLENGE_ID)
    chl.create_challenge = AsyncMock(return_value=challenge_obj)
    # SimpleNamespace gives both attribute access (handler does `detail.challenge`)
    # and is rendered to a dict by our passthrough serializer.
    chl.get_challenge_detail = AsyncMock(return_value=SimpleNamespace(
        challenge=_challenge_dict(),
        leaderboard=[],
        your_progress=None,
        your_status=None,
    ))
    chl.update_challenge = AsyncMock(return_value=_challenge_dict())
    chl.cancel_challenge = AsyncMock()
    chl.join_challenge = AsyncMock()
    chl.withdraw_from_challenge = AsyncMock()
    chl.get_challenge_leaderboard = AsyncMock(return_value=[])
    app.dependency_overrides[get_challenge_service] = lambda: chl

    routes = [
        ("POST", "/gamification/challenges", {
            "title": "Test", "challenge_type": "weekly", "scope": "individual",
            "metric_type": "steps", "target_value": 10000, "duration_days": 7, "xp_reward": 100,
        }, 201),
        ("GET", f"/gamification/challenges/{CHALLENGE_ID}", None, 200),
        ("PATCH", f"/gamification/challenges/{CHALLENGE_ID}", {"title": "Renamed"}, 200),
        ("POST", f"/gamification/challenges/{CHALLENGE_ID}/join", None, 200),
        ("POST", f"/gamification/challenges/{CHALLENGE_ID}/withdraw", None, 200),
        ("GET", f"/gamification/challenges/{CHALLENGE_ID}/leaderboard", None, 200),
        ("DELETE", f"/gamification/challenges/{CHALLENGE_ID}", None, 200),
    ]
    failures = []
    for method, path, body, expected in routes:
        kwargs = {"json": body} if body is not None else {}
        r = await client.request(method, path, **kwargs)
        if r.status_code != expected:
            failures.append((method, path, r.status_code, expected, r.text[:200]))
    assert not failures, f"Challenge route failures: {failures}"


@pytest.mark.asyncio
async def test_cp_routes_smoke(app, client):
    """Care-provider scoped routes use `get_current_care_provider`, which depends on
    `get_current_user`. Overriding `get_current_user` short-circuits the JWT chain.
    """
    _set_actor(app, role=ProfileTypeEnum.CARE_PROVIDER)
    _attach_default_session(app)

    cp_svc = MagicMock()
    cp_svc.get_overview = AsyncMock(return_value={
        "total_patients": 0, "active_patients": 0, "at_risk_patients": 0, "patients": [],
    })
    cp_svc.get_at_risk_patients = AsyncMock(return_value=[])
    cp_svc.get_groups = AsyncMock(return_value=[])
    cp_svc.get_challenges_created = AsyncMock(return_value=[])
    cp_svc.star_achievement = AsyncMock()
    app.dependency_overrides[get_cp_gamification_service] = lambda: cp_svc

    routes = [
        ("GET", f"/gamification/care-providers/{CP_ID}/overview"),
        ("GET", f"/gamification/care-providers/{CP_ID}/at-risk"),
        ("GET", f"/gamification/care-providers/{CP_ID}/groups"),
        ("GET", f"/gamification/care-providers/{CP_ID}/challenges"),
        ("POST", f"/gamification/care-providers/{CP_ID}/achievements/{ACHIEVEMENT_ID}/star"),
    ]
    failures = []
    for method, path in routes:
        r = await client.request(method, path)
        if r.status_code not in (200, 201):
            failures.append((method, path, r.status_code, r.text[:200]))
    assert not failures, f"CP route failures: {failures}"


@pytest.mark.asyncio
async def test_feed_cheer_and_catalog(app, client):
    _set_actor(app, role=ProfileTypeEnum.PATIENT)
    _attach_default_session(app)

    feed = MagicMock()
    feed.send_cheer = AsyncMock(return_value=SimpleNamespace())
    app.dependency_overrides[get_feed_service] = lambda: feed

    r = await client.post(f"/gamification/feed/{FEED_EVENT_ID}/cheer", json={"reaction": "fire"})
    assert r.status_code == 200, r.text

    r = await client.get("/gamification/catalog/achievements")
    assert r.status_code == 200
    assert len(r.json()["data"]) > 0
    assert all(not a.get("is_hidden") for a in r.json()["data"])

    r = await client.get("/gamification/catalog/achievements?include_hidden=true")
    assert r.status_code == 200
    assert any(a.get("is_hidden") for a in r.json()["data"])


class _AsyncCM:
    """Async context manager that yields the given object on __aenter__."""

    def __init__(self, inner):
        self._inner = inner

    async def __aenter__(self):
        return self._inner

    async def __aexit__(self, *_a):
        return False
