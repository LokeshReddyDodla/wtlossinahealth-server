from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]


class ExprStub:
    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, _name):
        return self

    def __eq__(self, _other):
        return self

    def __ne__(self, _other):
        return self

    def __lt__(self, _other):
        return self

    def __le__(self, _other):
        return self

    def __gt__(self, _other):
        return self

    def __ge__(self, _other):
        return self

    def __and__(self, _other):
        return self

    def __or__(self, _other):
        return self

    def in_(self, _other):
        return self

    def is_(self, _other):
        return self

    def is_not(self, _other):
        return self

    def desc(self):
        return self

    def between(self, *_args, **_kwargs):
        return self

    def label(self, _value):
        return self

    def select_from(self, *_args, **_kwargs):
        return self

    def where(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def outerjoin(self, *_args, **_kwargs):
        return self

    def group_by(self, *_args, **_kwargs):
        return self

    def distinct(self):
        return self


class QueryStub(ExprStub):
    pass


class EnumValue:
    def __init__(self, value: str):
        self.value = value

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        return isinstance(other, EnumValue) and self.value == other.value


def model_class(name: str, *field_names: str):
    attrs = {field_name: ExprStub() for field_name in field_names}
    attrs["__init__"] = lambda self, **kwargs: self.__dict__.update(kwargs)
    return type(name, (), attrs)


class FakeScalarResult:
    def __init__(self, values=None, scalar=None):
        self._values = list(values or [])
        self._scalar = scalar

    def all(self):
        return list(self._values)

    def first(self):
        return self._values[0] if self._values else None

    def scalar(self):
        if self._scalar is not None:
            return self._scalar
        return self._values[0] if self._values else None

    def scalars(self):
        return self


class FakeSession:
    def __init__(self, results=None):
        self._results = list(results or [])
        self.added = []
        self.commit_count = 0
        self.refresh_count = 0
        self.expire_all_count = 0

    async def execute(self, _query):
        if not self._results:
            raise AssertionError("No fake result queued for execute()")
        result = self._results.pop(0)
        if callable(result):
            return result(_query)
        return result

    def add(self, value):
        self.added.append(value)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _value):
        self.refresh_count += 1

    async def flush(self):
        return None

    async def rollback(self):
        return None

    async def expire_all(self):
        self.expire_all_count += 1


def make_module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value
    return _fn


def base_stubs() -> dict[str, types.ModuleType]:
    async def _get_patient_timezone(*_args, **_kwargs):
        return None

    sqlalchemy = make_module(
        "sqlalchemy",
        func=SimpleNamespace(
            count=lambda *a, **k: ExprStub(),
            sum=lambda *a, **k: ExprStub(),
            coalesce=lambda *a, **k: ExprStub(),
            max=lambda *a, **k: ExprStub(),
            date=lambda *a, **k: ExprStub(),
            distinct=lambda *a, **k: ExprStub(),
            extract=lambda *a, **k: ExprStub(),
        ),
        select=lambda *a, **k: QueryStub(),
        delete=lambda *a, **k: QueryStub(),
        and_=lambda *a, **k: ExprStub(),
        or_=lambda *a, **k: ExprStub(),
    )

    gamification_models = make_module(
        "lib.models.gamification",
        Achievement=model_class(
            "Achievement",
            "achievement_id",
            "slug",
            "title",
            "description",
            "icon",
            "category",
            "tier",
            "xp_reward",
            "is_hidden",
            "is_progressive",
            "sort_order",
        ),
        Challenge=model_class(
            "Challenge",
            "challenge_id",
            "is_active",
            "end_date",
            "start_date",
            "metric_type",
            "title",
            "scope",
        ),
        ChallengeParticipant=model_class(
            "ChallengeParticipant",
            "challenge_id",
            "participant_id",
            "participant_type",
            "status",
            "current_value",
            "rank",
            "xp_earned",
            "completed_at",
            "id",
        ),
        Group=model_class(
            "Group",
            "group_id",
            "name",
            "created_by_id",
            "created_by_type",
            "is_active",
            "description",
            "group_type",
            "facility_id",
            "max_members",
            "created_at",
        ),
        GroupMember=model_class(
            "GroupMember",
            "group_id",
            "patient_id",
            "is_active",
            "role",
            "joined_at",
            "left_at",
            "id",
        ),
        PatientAchievement=model_class(
            "PatientAchievement",
            "id",
            "patient_id",
            "achievement_id",
            "earned_at",
            "starred_by",
            "starred_at",
        ),
        PlayerProfile=model_class(
            "PlayerProfile",
            "patient_id",
            "leaderboard_visibility",
            "level",
            "current_streak",
            "total_xp",
            "streak_freezes",
            "longest_streak",
            "streak_frozen_on",
        ),
        DailyTask=model_class(
            "DailyTask",
            "task_id",
            "patient_id",
            "task_date",
            "task_type",
            "title",
            "description",
            "status",
            "current_value",
            "target_value",
            "source_type",
            "source_id",
            "xp_reward",
            "completed_at",
        ),
        LeaderboardEntry=model_class(
            "LeaderboardEntry",
            "board_type",
            "board_scope",
            "scope_id",
            "patient_id",
            "rank",
            "metric_value",
            "period_start",
            "period_end",
        ),
        XPLedgerEntry=model_class(
            "XPLedgerEntry",
            "patient_id",
            "created_at",
            "xp_amount",
        ),
        CareProvider=model_class(
            "CareProvider",
            "care_provider_id",
            "permissions",
        ),
        WeeklyQuest=model_class(
            "WeeklyQuest",
            "quest_id",
            "patient_id",
            "week_start",
            "quest_type",
            "title",
            "description",
            "target_value",
            "current_value",
            "xp_reward",
            "status",
            "completed_at",
        ),
        ActivityFeedEvent=model_class(
            "ActivityFeedEvent",
            "feed_id",
            "actor_id",
            "visibility",
            "group_id",
            "event_type",
            "event_data",
            "created_at",
            "expires_at",
        ),
        Buddy=model_class(
            "Buddy",
            "buddy_id",
            "requester_id",
            "accepter_id",
            "status",
            "buddy_streak",
            "created_at",
        ),
        Cheer=model_class(
            "Cheer",
            "cheer_id",
            "sender_id",
            "recipient_id",
            "feed_event_id",
            "reaction",
            "created_at",
        ),
    )

    gamification_schemas = make_module(
        "lib.schemas.gamification",
        SourceType=SimpleNamespace(
            HABIT=EnumValue("habit"),
            DIET_PLAN=EnumValue("diet_plan"),
            FITNESS_PLAN=EnumValue("fitness_plan"),
            CHALLENGE=EnumValue("challenge"),
        ),
        TaskType=SimpleNamespace(
            LOG_MEAL=EnumValue("LOG_MEAL"),
            HIT_CALORIE_TARGET=EnumValue("HIT_CALORIE_TARGET"),
            HIT_PROTEIN_TARGET=EnumValue("HIT_PROTEIN_TARGET"),
            HIT_STEP_GOAL=EnumValue("HIT_STEP_GOAL"),
            COMPLETE_WORKOUT=EnumValue("COMPLETE_WORKOUT"),
            LOG_SLEEP=EnumValue("LOG_SLEEP"),
            LOG_MOOD=EnumValue("LOG_MOOD"),
            LOG_GLUCOSE=EnumValue("LOG_GLUCOSE"),
            LOG_WEIGHT=EnumValue("LOG_WEIGHT"),
            CHALLENGE_TASK=EnumValue("CHALLENGE_TASK"),
        ),
        ChallengeDetailResponse=type(
            "ChallengeDetailResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        ChallengeParticipantResponse=type(
            "ChallengeParticipantResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        ChallengeResponse=type(
            "ChallengeResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        ChallengeCreateInput=type(
            "ChallengeCreateInput",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        LeaderboardEntryResponse=type(
            "LeaderboardEntryResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        LeaderboardResponse=type(
            "LeaderboardResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        CPGamificationOverview=type(
            "CPGamificationOverview",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        PatientEngagementSummary=type(
            "PatientEngagementSummary",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        FeedEventResponse=type(
            "FeedEventResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        GroupResponse=type(
            "GroupResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        GroupCreateInput=type(
            "GroupCreateInput",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        GroupMemberResponse=type(
            "GroupMemberResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        BuddyResponse=type(
            "BuddyResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        BuddyRequestInput=type(
            "BuddyRequestInput",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        BuddyProgressResponse=type(
            "BuddyProgressResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        AchievementResponse=type(
            "AchievementResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        DailyProgressResponse=type(
            "DailyProgressResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        DailyTaskResponse=type(
            "DailyTaskResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        GamificationContext=type(
            "GamificationContext",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        PlayerProfileResponse=type(
            "PlayerProfileResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        PlayerProfileUpdate=type(
            "PlayerProfileUpdate",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        TaskCompletionResponse=type(
            "TaskCompletionResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        WeeklyQuestResponse=type(
            "WeeklyQuestResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        XPHistoryEntry=type(
            "XPHistoryEntry",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        XPHistoryResponse=type(
            "XPHistoryResponse",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        CheerInput=type(
            "CheerInput",
            (),
            {"__init__": lambda self, **kw: self.__dict__.update(kw)},
        ),
        TaskStatus=SimpleNamespace(
            COMPLETED=SimpleNamespace(value="completed"),
            PENDING=SimpleNamespace(value="pending"),
            ACTIVE=SimpleNamespace(value="active"),
            EXPIRED=SimpleNamespace(value="expired"),
        ),
        ParticipantStatus=SimpleNamespace(
            ACTIVE=EnumValue("active"),
            COMPLETED=EnumValue("completed"),
            WITHDRAWN=EnumValue("withdrawn"),
        ),
        ParticipantType=SimpleNamespace(
            PATIENT=EnumValue("patient"),
            GROUP=EnumValue("group"),
        ),
        BuddyStatus=SimpleNamespace(
            ACTIVE=EnumValue("active"),
            PENDING=EnumValue("pending"),
            REMOVED=EnumValue("removed"),
        ),
        CreatorType=SimpleNamespace(
            CARE_PROVIDER=EnumValue("care_provider"),
            SYSTEM=EnumValue("system"),
        ),
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

    return {
        "sqlalchemy": sqlalchemy,
        "sqlalchemy.ext": make_module("sqlalchemy.ext"),
        "sqlalchemy.ext.asyncio": make_module(
            "sqlalchemy.ext.asyncio",
            AsyncSession=type("AsyncSession", (), {}),
        ),
        "lib.core.postgres_store": make_module(
            "lib.core.postgres_store",
            PostgresStore=type("PostgresStore", (), {}),
        ),
        "lib.models.gamification": gamification_models,
        "lib.models.patient": make_module(
            "lib.models.patient",
            Patient=model_class("Patient", "patient_id", "locale", "first_name", "health_facility_id"),
        ),
        "lib.models.associations": make_module(
            "lib.models.associations",
            patient_care_provider_association=SimpleNamespace(
                c=SimpleNamespace(
                    patient_id=ExprStub(),
                    care_provider_id=ExprStub(),
                )
            ),
        ),
        "lib.models.patient_diet_plan": make_module(
            "lib.models.patient_diet_plan",
            PatientDietPlan=model_class(
                "PatientDietPlan",
                "patient_id",
                "status",
                "start_date",
                "diet_plan_id",
                "calories",
                "protein",
                "content",
            ),
        ),
        "lib.models.patient_fitness_plan": make_module(
            "lib.models.patient_fitness_plan",
            PatientFitnessPlan=model_class(
                "PatientFitnessPlan",
                "patient_id",
                "status",
                "start_date",
                "fitness_plan_id",
                "steps_goal",
                "content",
            ),
        ),
        "lib.schemas.gamification": gamification_schemas,
        "loguru": make_module(
            "loguru",
            logger=SimpleNamespace(
                info=lambda *a, **k: None,
                warning=lambda *a, **k: None,
                debug=lambda *a, **k: None,
                opt=lambda *a, **k: SimpleNamespace(
                    warning=lambda *aa, **kk: None,
                    debug=lambda *aa, **kk: None,
                ),
            ),
        ),
        "lib.services.gamification.time_utils": make_module(
            "lib.services.gamification.time_utils",
            local_today=lambda _tz=None: None,
            local_now=lambda _tz=None, now=None: None,
            resolve_timezone=lambda _tz=None: None,
            naive_day_bounds_for_local_date=lambda *_a, **_k: (None, None),
            matches_local_hour=lambda *_a, **_k: False,
            get_patient_timezone=_get_patient_timezone,
        ),
        "lib.services.gamification.notifications": make_module(
            "lib.services.gamification.notifications",
            send_gamification_notification=lambda *a, **k: None,
        ),
        "lib.services.gamification.queries": make_module(
            "lib.services.gamification.queries",
            active_group_ids=_async_return([]),
            active_challenge_participations=_async_return([]),
        ),
        "lib.services.gamification.profile_utils": make_module(
            "lib.services.gamification.profile_utils",
            get_or_create_profile=_async_return(None),
        ),
        "lib.services.gamification.xp_service": make_module(
            "lib.services.gamification.xp_service",
            XPService=type("XPService", (), {}),
            streak_multiplier=lambda streak: 1.2 if streak >= 14 else 1.0,
        ),
        "lib.services.gamification.achievement_evaluator": make_module(
            "lib.services.gamification.achievement_evaluator",
            AchievementEvaluator=type("AchievementEvaluator", (), {}),
        ),
        "lib.services.gamification.task_generator": make_module(
            "lib.services.gamification.task_generator",
            TaskGeneratorService=type("TaskGeneratorService", (), {}),
        ),
        "lib.utils.postgres_session_decorator": make_module(
            "lib.utils.postgres_session_decorator",
            with_postgres_session=lambda fn: fn,
        ),
    }


def load_module(monkeypatch, relative_path: str, module_name: str, extra_stubs=None):
    stubs = base_stubs()
    for name, module in (extra_stubs or {}).items():
        stubs[name] = module
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module
