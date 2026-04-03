from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


def _make_module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _load_module(monkeypatch, relative_path: str, module_name: str, stubs: dict[str, types.ModuleType]):
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _base_stubs() -> dict[str, types.ModuleType]:
    sqlalchemy = _make_module(
        "sqlalchemy",
        func=SimpleNamespace(count=lambda *a, **k: None, sum=lambda *a, **k: None, coalesce=lambda *a, **k: None),
        select=lambda *a, **k: None,
        delete=lambda *a, **k: None,
        or_=lambda *a, **k: None,
    )
    sqlalchemy_ext = _make_module("sqlalchemy.ext")
    sqlalchemy_asyncio = _make_module("sqlalchemy.ext.asyncio", AsyncSession=type("AsyncSession", (), {}))

    gamification_models = _make_module(
        "lib.models.gamification",
        Challenge=type("Challenge", (), {}),
        ChallengeParticipant=type("ChallengeParticipant", (), {}),
        Group=type("Group", (), {}),
        GroupMember=type("GroupMember", (), {}),
        PlayerProfile=type("PlayerProfile", (), {}),
        DailyTask=type("DailyTask", (), {}),
        LeaderboardEntry=type("LeaderboardEntry", (), {}),
        XPLedgerEntry=type("XPLedgerEntry", (), {}),
        ActivityFeedEvent=type("ActivityFeedEvent", (), {}),
        Buddy=type("Buddy", (), {}),
        Cheer=type("Cheer", (), {}),
    )

    gamification_schemas = _make_module(
        "lib.schemas.gamification",
        ChallengeDetailResponse=type("ChallengeDetailResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        ChallengeParticipantResponse=type("ChallengeParticipantResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        ChallengeResponse=type("ChallengeResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        LeaderboardEntryResponse=type("LeaderboardEntryResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        LeaderboardResponse=type("LeaderboardResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        FeedEventResponse=type("FeedEventResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        TaskStatus=SimpleNamespace(COMPLETED=SimpleNamespace(value="completed")),
        title_for_level=lambda level: {
            1: "Newcomer",
            5: "Explorer",
            10: "Committed",
            15: "Achiever",
            20: "Warrior",
        }.get(level, "Legend"),
        xp_for_level=lambda level: 0 if level <= 1 else int(200 * (level ** 1.5)),
    )

    return {
        "sqlalchemy": sqlalchemy,
        "sqlalchemy.ext": sqlalchemy_ext,
        "sqlalchemy.ext.asyncio": sqlalchemy_asyncio,
        "lib.core.postgres_store": _make_module("lib.core.postgres_store", PostgresStore=type("PostgresStore", (), {})),
        "lib.models.gamification": gamification_models,
        "lib.models.patient": _make_module("lib.models.patient", Patient=type("Patient", (), {})),
        "lib.schemas.gamification": gamification_schemas,
        "lib.services.gamification.time_utils": _make_module(
            "lib.services.gamification.time_utils",
            local_today=lambda _tz=None: None,
            naive_day_bounds_for_local_date=lambda *_a, **_k: (None, None),
        ),
        "lib.services.gamification.notifications": _make_module(
            "lib.services.gamification.notifications",
            send_gamification_notification=lambda *a, **k: None,
        ),
        "lib.services.gamification.xp_service": _make_module(
            "lib.services.gamification.xp_service",
            XPService=type("XPService", (), {}),
        ),
        "lib.utils.postgres_session_decorator": _make_module(
            "lib.utils.postgres_session_decorator",
            with_postgres_session=lambda fn: fn,
        ),
    }


def test_xp_helpers_follow_streak_breakpoints(monkeypatch):
    module = _load_module(
        monkeypatch,
        "lib/services/gamification/xp_service.py",
        "test_xp_service_module",
        _base_stubs(),
    )

    assert module.streak_multiplier(0) == 1.0
    assert module.streak_multiplier(7) == 1.1
    assert module.streak_multiplier(14) == 1.2
    assert module.streak_multiplier(30) == 1.3
    assert module.streak_multiplier(60) == 1.4
    assert module.streak_multiplier(90) == 1.5


def test_level_from_xp_reaches_known_thresholds(monkeypatch):
    module = _load_module(
        monkeypatch,
        "lib/services/gamification/xp_service.py",
        "test_xp_service_module_levels",
        _base_stubs(),
    )

    assert module.level_from_xp(0) == 1
    assert module.level_from_xp(module.xp_for_level(5)) == 5
    assert module.level_from_xp(module.xp_for_level(10)) == 10


def test_challenge_reward_policy_handles_group_and_winner_bonus(monkeypatch):
    module = _load_module(
        monkeypatch,
        "lib/services/gamification/challenge_service.py",
        "test_challenge_service_rewards",
        _base_stubs(),
    )
    service = object.__new__(module.ChallengeService)

    challenge = SimpleNamespace(scope="group_competitive", xp_reward=50, bonus_xp_winner=25)
    participant = SimpleNamespace(participant_type="group", status="active", rank=1)

    assert service._participant_reward_xp(challenge, participant) == 75


def test_challenge_reward_policy_requires_completion_for_cooperative(monkeypatch):
    module = _load_module(
        monkeypatch,
        "lib/services/gamification/challenge_service.py",
        "test_challenge_service_coop_rewards",
        _base_stubs(),
    )
    service = object.__new__(module.ChallengeService)

    challenge = SimpleNamespace(scope="group_cooperative", xp_reward=80, bonus_xp_winner=0)
    incomplete = SimpleNamespace(participant_type="group", status="active", rank=2)
    complete = SimpleNamespace(participant_type="group", status="completed", rank=2)

    assert service._participant_reward_xp(challenge, incomplete) == 0
    assert service._participant_reward_xp(challenge, complete) == 80


def test_leaderboard_identity_visibility_rules(monkeypatch):
    module = _load_module(
        monkeypatch,
        "lib/services/gamification/leaderboard_service.py",
        "test_leaderboard_service_visibility",
        _base_stubs(),
    )
    service = object.__new__(module.LeaderboardService)

    viewer_id = uuid4()
    subject_id = uuid4()

    assert service._is_identity_visible(
        viewer_id=viewer_id,
        subject_id=viewer_id,
        visibility="anonymous",
        board_scope="global",
    ) is True
    assert service._is_identity_visible(
        viewer_id=viewer_id,
        subject_id=subject_id,
        visibility="public",
        board_scope="global",
    ) is True
    assert service._is_identity_visible(
        viewer_id=viewer_id,
        subject_id=subject_id,
        visibility="group_only",
        board_scope="group",
    ) is True
    assert service._is_identity_visible(
        viewer_id=viewer_id,
        subject_id=subject_id,
        visibility="group_only",
        board_scope="challenge",
    ) is True
    assert service._is_identity_visible(
        viewer_id=viewer_id,
        subject_id=subject_id,
        visibility="group_only",
        board_scope="global",
    ) is False


def test_feed_identity_visibility_rules(monkeypatch):
    module = _load_module(
        monkeypatch,
        "lib/services/gamification/feed_service.py",
        "test_feed_service_visibility",
        _base_stubs(),
    )
    service = object.__new__(module.FeedService)

    viewer_id = uuid4()
    actor_id = uuid4()

    assert service._is_identity_visible(
        viewer_id=viewer_id,
        actor_id=viewer_id,
        visibility="anonymous",
        context="group",
    ) is True
    assert service._is_identity_visible(
        viewer_id=viewer_id,
        actor_id=actor_id,
        visibility="anonymous",
        context="buddy",
    ) is True
    assert service._is_identity_visible(
        viewer_id=viewer_id,
        actor_id=actor_id,
        visibility="public",
        context="public",
    ) is True
    assert service._is_identity_visible(
        viewer_id=viewer_id,
        actor_id=actor_id,
        visibility="group_only",
        context="group",
    ) is True
    assert service._is_identity_visible(
        viewer_id=viewer_id,
        actor_id=actor_id,
        visibility="group_only",
        context="public",
    ) is False
