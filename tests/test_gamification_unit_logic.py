from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]


class _StrEnumMember(str):
    """Hashable stub that behaves like a str enum member."""
    def __new__(cls, value: str):
        obj = str.__new__(cls, value)
        obj._value = value
        return obj

    @property
    def value(self):
        return self._value


def _make_str_enum(name: str, **members):
    """Create a SimpleNamespace whose members are hashable str-like objects."""
    ns = SimpleNamespace(**{k: _StrEnumMember(v) for k, v in members.items()})
    return ns


def _make_module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


async def _async_noop(*_a, **_k):
    """Awaitable no-op for stubbing async functions in tests."""
    return None


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
        func=SimpleNamespace(count=lambda *a, **k: None, sum=lambda *a, **k: None, coalesce=lambda *a, **k: None, distinct=lambda *a, **k: None, date=lambda *a, **k: None, extract=lambda *a, **k: None, max=lambda *a, **k: None),
        select=lambda *a, **k: None,
        delete=lambda *a, **k: None,
        or_=lambda *a, **k: None,
        and_=lambda *a, **k: None,
    )
    sqlalchemy_ext = _make_module("sqlalchemy.ext")
    sqlalchemy_asyncio = _make_module("sqlalchemy.ext.asyncio", AsyncSession=type("AsyncSession", (), {}))

    gamification_models = _make_module(
        "lib.models.gamification",
        Achievement=type("Achievement", (), {}),
        ActivityFeedEvent=type("ActivityFeedEvent", (), {}),
        Buddy=type("Buddy", (), {}),
        Challenge=type("Challenge", (), {}),
        ChallengeParticipant=type("ChallengeParticipant", (), {}),
        Cheer=type("Cheer", (), {}),
        DailyTask=type("DailyTask", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        Group=type("Group", (), {}),
        GroupMember=type("GroupMember", (), {}),
        LeaderboardEntry=type("LeaderboardEntry", (), {}),
        PatientAchievement=type("PatientAchievement", (), {}),
        PlayerProfile=type("PlayerProfile", (), {}),
        WeeklyQuest=type("WeeklyQuest", (), {}),
        XPLedgerEntry=type("XPLedgerEntry", (), {}),
    )

    gamification_schemas = _make_module(
        "lib.schemas.gamification",
        ChallengeDetailResponse=type("ChallengeDetailResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        ChallengeParticipantResponse=type("ChallengeParticipantResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        ChallengeResponse=type("ChallengeResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        LeaderboardEntryResponse=type("LeaderboardEntryResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        LeaderboardResponse=type("LeaderboardResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        FeedEventResponse=type("FeedEventResponse", (), {"__init__": lambda self, **kw: self.__dict__.update(kw)}),
        TaskStatus=SimpleNamespace(COMPLETED=SimpleNamespace(value="completed"), PENDING=SimpleNamespace(value="pending")),
        TaskType=_make_str_enum(
            "TaskType",
            LOG_MEAL="LOG_MEAL", HIT_CALORIE_TARGET="HIT_CALORIE_TARGET",
            HIT_PROTEIN_TARGET="HIT_PROTEIN_TARGET", HIT_STEP_GOAL="HIT_STEP_GOAL",
            COMPLETE_WORKOUT="COMPLETE_WORKOUT", LOG_SLEEP="LOG_SLEEP",
            LOG_MOOD="LOG_MOOD", LOG_GLUCOSE="LOG_GLUCOSE",
            LOG_WEIGHT="LOG_WEIGHT", CHALLENGE_TASK="CHALLENGE_TASK",
            TAKE_MEDICATION_MORNING="TAKE_MEDICATION_MORNING",
            TAKE_MEDICATION_AFTERNOON="TAKE_MEDICATION_AFTERNOON",
            TAKE_MEDICATION_EVENING="TAKE_MEDICATION_EVENING",
            TAKE_MEDICATION_NIGHT="TAKE_MEDICATION_NIGHT",
            FOLLOW_UP_APPOINTMENT="FOLLOW_UP_APPOINTMENT",
        ),
        SourceType=_make_str_enum(
            "SourceType",
            DIET_PLAN="diet_plan", FITNESS_PLAN="fitness_plan",
            HABIT="habit", QUEST="quest", CHALLENGE="challenge",
            MEDICATION="medication", PRESCRIPTION="prescription",
        ),
        ParticipantStatus=_make_str_enum("ParticipantStatus", ACTIVE="active", COMPLETED="completed", WITHDRAWN="withdrawn"),
        ParticipantType=_make_str_enum("ParticipantType", PATIENT="patient", GROUP="group"),
        BuddyStatus=_make_str_enum("BuddyStatus", ACTIVE="active", PENDING="pending", REMOVED="removed"),
        CreatorType=_make_str_enum("CreatorType", CARE_PROVIDER="care_provider"),
        DAILY_XP_CAP=500,
        BUDDY_REQUESTS_PER_DAY=10,
        MAX_LEVEL=100,
        MAX_ACTIVE_BUDDIES=3,
        CHEERS_PER_DAY_LIMIT=3,
        CHEER_XP_REWARD=5,
        FEED_EXPIRY_DAYS=30,
        STEP_GOAL_THRESHOLD_PCT=0.80,
        CALORIE_TOLERANCE_PCT=0.15,
        PROTEIN_TOLERANCE_PCT=0.10,
        MANUALLY_COMPLETABLE_TASKS={"LOG_MEAL", "LOG_SLEEP", "LOG_MOOD", "LOG_GLUCOSE", "LOG_WEIGHT"},
        title_for_level=lambda level: {
            1: "Newcomer",
            5: "Explorer",
            10: "Committed",
            15: "Achiever",
            20: "Warrior",
        }.get(level, "Legend"),
        xp_for_level=lambda level: 0 if level <= 1 else int(200 * (level ** 1.5)),
    )

    # Stub lib.models as a package so service modules importing
    # `from lib.models.x import Y` don't trigger the real package init.
    lib_models_pkg = _make_module("lib.models", Base=type("Base", (), {}))
    lib_models_pkg.__path__ = []

    return {
        "sqlalchemy": sqlalchemy,
        "sqlalchemy.ext": sqlalchemy_ext,
        "sqlalchemy.ext.asyncio": sqlalchemy_asyncio,
        "sqlalchemy.orm": _make_module(
            "sqlalchemy.orm",
            declarative_base=lambda: type("Base", (), {}),
            sessionmaker=lambda *a, **k: None,
            relationship=lambda *a, **k: None,
            selectinload=lambda *a, **k: None,
        ),
        "lib.core.postgres_store": _make_module("lib.core.postgres_store", PostgresStore=type("PostgresStore", (), {})),
        "lib.models": lib_models_pkg,
        "lib.models.gamification": gamification_models,
        "lib.models.patient": _make_module("lib.models.patient", Patient=type("Patient", (), {})),
        "lib.models.patient_diabetic_history": _make_module(
            "lib.models.patient_diabetic_history",
            PatientDiabeticHistory=type("PatientDiabeticHistory", (), {}),
        ),
        "lib.models.patient_medication": _make_module(
            "lib.models.patient_medication",
            PatientMedication=type("PatientMedication", (), {}),
        ),
        "lib.models.patient_prescription": _make_module(
            "lib.models.patient_prescription",
            PatientPrescription=type("PatientPrescription", (), {}),
        ),
        "lib.schemas.gamification": gamification_schemas,
        "lib.services.gamification.time_utils": _make_module(
            "lib.services.gamification.time_utils",
            local_today=lambda _tz=None: None,
            naive_day_bounds_for_local_date=lambda *_a, **_k: (None, None),
        ),
        "lib.services.gamification.notifications": _make_module(
            "lib.services.gamification.notifications",
            send_gamification_notification=_async_noop,
        ),
        "lib.services.gamification.xp_service": _make_module(
            "lib.services.gamification.xp_service",
            XPService=type("XPService", (), {}),
            streak_multiplier=lambda s: 1.0,
        ),
        "lib.services.gamification.queries": _make_module(
            "lib.services.gamification.queries",
            active_group_ids=lambda *a, **k: [],
            active_challenge_participations=lambda *a, **k: [],
        ),
        "lib.services.gamification.profile_utils": _make_module(
            "lib.services.gamification.profile_utils",
            get_or_create_profile=lambda *a, **k: None,
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
