from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class TaskType(str, Enum):
    LOG_MEAL = "LOG_MEAL"
    HIT_CALORIE_TARGET = "HIT_CALORIE_TARGET"
    HIT_PROTEIN_TARGET = "HIT_PROTEIN_TARGET"
    HIT_STEP_GOAL = "HIT_STEP_GOAL"
    COMPLETE_WORKOUT = "COMPLETE_WORKOUT"
    LOG_SLEEP = "LOG_SLEEP"
    LOG_MOOD = "LOG_MOOD"
    LOG_GLUCOSE = "LOG_GLUCOSE"
    LOG_WEIGHT = "LOG_WEIGHT"
    TAKE_MEDICATION_MORNING = "TAKE_MEDICATION_MORNING"
    TAKE_MEDICATION_AFTERNOON = "TAKE_MEDICATION_AFTERNOON"
    TAKE_MEDICATION_EVENING = "TAKE_MEDICATION_EVENING"
    TAKE_MEDICATION_NIGHT = "TAKE_MEDICATION_NIGHT"
    FOLLOW_UP_APPOINTMENT = "FOLLOW_UP_APPOINTMENT"
    WEEKLY_QUEST = "WEEKLY_QUEST"
    CHALLENGE_TASK = "CHALLENGE_TASK"


class TaskStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    EXPIRED = "expired"


class SourceType(str, Enum):
    DIET_PLAN = "diet_plan"
    FITNESS_PLAN = "fitness_plan"
    HABIT = "habit"
    QUEST = "quest"
    CHALLENGE = "challenge"
    MEDICATION = "medication"
    PRESCRIPTION = "prescription"


class AchievementCategory(str, Enum):
    CONSISTENCY = "consistency"
    NUTRITION = "nutrition"
    FITNESS = "fitness"
    WELLNESS = "wellness"
    SOCIAL = "social"
    MILESTONE = "milestone"


class AchievementTier(str, Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


class BuddyStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REMOVED = "removed"


class GroupType(str, Enum):
    CARE_PROVIDER = "care_provider"
    FACILITY = "facility"
    PATIENT_CREATED = "patient_created"


class GroupMemberRole(str, Enum):
    MEMBER = "member"
    ADMIN = "admin"
    MODERATOR = "moderator"


class ChallengeType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"
    SEASONAL = "seasonal"


class ChallengeScope(str, Enum):
    INDIVIDUAL = "individual"
    GROUP_COMPETITIVE = "group_competitive"
    GROUP_COOPERATIVE = "group_cooperative"
    FACILITY = "facility"


class ChallengeMetricType(str, Enum):
    STEPS = "steps"
    MEALS_LOGGED = "meals_logged"
    WORKOUTS = "workouts"
    XP_EARNED = "xp_earned"
    STREAK_DAYS = "streak_days"
    CALORIE_TARGET_HITS = "calorie_target_hits"
    CUSTOM = "custom"


class LeaderboardVisibility(str, Enum):
    ANONYMOUS = "anonymous"
    GROUP_ONLY = "group_only"
    PUBLIC = "public"


class Reaction(str, Enum):
    APPLAUSE = "applause"
    STRONG = "strong"
    FIRE = "fire"
    STAR = "star"


class FeedEventType(str, Enum):
    ACHIEVEMENT_EARNED = "achievement_earned"
    LEVEL_UP = "level_up"
    STREAK_MILESTONE = "streak_milestone"
    CHALLENGE_COMPLETED = "challenge_completed"
    CHALLENGE_WON = "challenge_won"
    CHEER_SENT = "cheer_sent"


class ParticipantStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    WITHDRAWN = "withdrawn"


class ParticipantType(str, Enum):
    PATIENT = "patient"
    GROUP = "group"


class FeedVisibility(str, Enum):
    BUDDY = "buddy"
    GROUP = "group"
    FACILITY = "facility"
    PUBLIC = "public"


class CreatorType(str, Enum):
    SYSTEM = "system"
    CARE_PROVIDER = "care_provider"
    FACILITY_ADMIN = "facility_admin"
    PATIENT = "patient"


# ── Constants ────────────────────────────────────────────────────────────────

STEP_GOAL_THRESHOLD_PCT = 0.80
CALORIE_TOLERANCE_PCT = 0.15
PROTEIN_TOLERANCE_PCT = 0.10
XP_LEVEL_BASE = 200
XP_LEVEL_EXPONENT = 1.5
MAX_STREAK_FREEZES = 3
FREEZE_EARN_INTERVAL_DAYS = 7
DAILY_XP_CAP = 500
MAX_ACTIVE_BUDDIES = 3
CHEERS_PER_DAY_LIMIT = 3
CHEER_XP_REWARD = 5
FEED_EXPIRY_DAYS = 30
LEADERBOARD_TOP_N = 100
CHALLENGE_LEADERBOARD_LIMIT = 20
BUDDY_REQUESTS_PER_DAY = 5
MAX_LEVEL = 200

# Task types that can be manually completed.
MANUALLY_COMPLETABLE_TASKS = {
    TaskType.TAKE_MEDICATION_MORNING.value,
    TaskType.TAKE_MEDICATION_AFTERNOON.value,
    TaskType.TAKE_MEDICATION_EVENING.value,
    TaskType.TAKE_MEDICATION_NIGHT.value,
    TaskType.FOLLOW_UP_APPOINTMENT.value,
}


# ── Level titles ─────────────────────────────────────────────────────────────

LEVEL_TITLES: Dict[int, str] = {
    1: "Newcomer",
    5: "Explorer",
    10: "Committed",
    15: "Achiever",
    20: "Warrior",
    30: "Champion",
    40: "Master",
    50: "Legend",
    75: "Mythic",
    100: "Immortal",
}


def title_for_level(level: int) -> str:
    title = "Newcomer"
    for threshold, name in sorted(LEVEL_TITLES.items()):
        if level >= threshold:
            title = name
    return title


def xp_for_level(level: int) -> int:
    """Cumulative XP needed to reach *level*."""
    if level <= 1:
        return 0
    return int(XP_LEVEL_BASE * (level ** XP_LEVEL_EXPONENT))


# ── Player Profile ───────────────────────────────────────────────────────────


class PlayerProfileResponse(BaseModel):
    player_profile_id: str
    patient_id: str
    total_xp: int
    level: int
    title: str
    current_streak: int
    longest_streak: int
    streak_freezes: int
    streak_multiplier: float
    last_active_date: Optional[date] = None
    buddy_code: Optional[str] = None
    leaderboard_visibility: str
    xp_to_next_level: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class PlayerProfileUpdate(BaseModel):
    leaderboard_visibility: Optional[LeaderboardVisibility] = None
    title_slug: Optional[str] = Field(None, max_length=50)


# ── Daily Tasks ──────────────────────────────────────────────────────────────


class DailyTaskResponse(BaseModel):
    task_id: str
    task_date: date
    task_type: str
    title: str
    description: Optional[str] = None
    source_type: str
    source_id: Optional[str] = None
    target_value: Optional[float] = None
    current_value: Optional[float] = None
    status: str
    xp_reward: int
    completed_at: Optional[datetime] = None


class DailyProgressResponse(BaseModel):
    date: date
    tasks: List[DailyTaskResponse]
    completed_count: int
    total_count: int
    xp_earned_today: int
    streak_status: str  # active | frozen | broken


class DailySummary(BaseModel):
    date: date
    completed_count: int
    total_count: int
    xp_earned: int
    active_day: bool
    tasks: List[DailyTaskResponse]


class DailyHistoryResponse(BaseModel):
    start_date: date
    end_date: date
    days: List[DailySummary]


class TaskCompletionResponse(BaseModel):
    task_id: str
    xp_earned: int
    new_total_xp: int
    level_up: bool
    new_level: int
    achievements_unlocked: List[AchievementResponse] = []


# ── Achievements ─────────────────────────────────────────────────────────────


class AchievementResponse(BaseModel):
    achievement_id: str
    slug: str
    title: str
    description: str
    icon: str
    category: str
    tier: str
    xp_reward: int
    is_hidden: bool
    is_progressive: bool
    earned: bool
    earned_at: Optional[datetime] = None
    progress_pct: float = 0.0
    starred_by: Optional[str] = None
    starred_at: Optional[datetime] = None


# ── Buddies ──────────────────────────────────────────────────────────────────


class BuddyRequestInput(BaseModel):
    accepter_id: UUID = Field(..., description="Patient ID of the buddy to add")


class BuddyRequestByCodeInput(BaseModel):
    buddy_code: str = Field(..., min_length=6, max_length=8)


class BuddyResponse(BaseModel):
    buddy_id: str
    buddy_patient_id: str
    buddy_name: Optional[str] = None
    status: str
    direction: Optional[str] = None  # "incoming" or "outgoing" (only set when status is "pending")
    buddy_streak: int
    buddy_streak_longest: int
    tasks_completed_today: int = 0
    tasks_total_today: int = 0
    created_at: datetime
    accepted_at: Optional[datetime] = None


class BuddyProgressResponse(BaseModel):
    buddy_patient_id: str
    buddy_name: Optional[str] = None
    level: int
    title: str
    current_streak: int
    tasks_completed_today: int
    tasks_total_today: int
    recent_achievements: List[str] = []


class BuddyDetailResponse(BaseModel):
    """Rich buddy details for the buddy profile/details screen.

    Works for BOTH preview (no relationship yet) and existing buddies.
    status="none" means no relationship — preview mode.
    """
    buddy_id: Optional[str] = None  # null if no relationship exists yet
    buddy_patient_id: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_picture: Optional[str] = None
    status: str  # none/pending/active/removed
    direction: Optional[str] = None  # outgoing/incoming for pending
    buddy_streak: int = 0
    buddy_streak_longest: int = 0
    level: int = 1
    title: Optional[str] = None
    total_xp: int = 0
    current_streak: int = 0  # buddy's personal streak
    longest_streak: int = 0
    tasks_completed_today: int = 0
    tasks_total_today: int = 0
    recent_achievements: List[str] = []
    created_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None


# ── Groups ───────────────────────────────────────────────────────────────────


class GroupCreateInput(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    group_type: GroupType
    facility_id: Optional[UUID] = None
    max_members: int = Field(50, ge=2, le=200)


class AvatarPreview(BaseModel):
    patient_id: str
    name: Optional[str] = None
    profile_picture: Optional[str] = None


class GroupResponse(BaseModel):
    group_id: str
    name: str
    description: Optional[str] = None
    group_type: str
    created_by_id: str
    created_by_type: str
    facility_id: Optional[str] = None
    invite_code: Optional[str] = None
    avatar_url: Optional[str] = None
    member_count: int = 0
    max_members: int
    is_active: bool
    created_at: datetime
    top_members: List[AvatarPreview] = []
    active_challenges: int = 0


class GroupMemberPreview(BaseModel):
    """Lightweight member info for group preview cards."""
    patient_id: str
    first_name: Optional[str] = None
    profile_picture: Optional[str] = None
    role: str  # member/admin/moderator


class GroupInfoResponse(BaseModel):
    """Rich group info for the group details/card screen."""
    group_id: str
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    group_type: str
    member_count: int
    max_members: int
    is_active: bool
    invite_code: Optional[str] = None
    your_role: Optional[str] = None  # member/admin/moderator/null if not a member
    top_members: List[GroupMemberPreview] = []  # first 5 active members
    created_at: datetime


class JoinByCodeInput(BaseModel):
    invite_code: str = Field(..., min_length=6, max_length=8)


class AddGroupMembersInput(BaseModel):
    patient_ids: List[UUID] = Field(..., min_length=1, max_length=50)


class GroupMemberResponse(BaseModel):
    patient_id: str
    patient_name: Optional[str] = None
    role: str
    level: int
    title: str
    current_streak: int
    joined_at: datetime


# ── Challenges ───────────────────────────────────────────────────────────────


class ChallengeCreateInput(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field(None, max_length=1000)
    challenge_type: ChallengeType
    scope: ChallengeScope
    metric_type: ChallengeMetricType
    target_value: float = Field(..., gt=0)
    duration_days: int = Field(..., ge=1, le=365)
    xp_reward: int = Field(..., ge=1, le=10000)
    bonus_xp_winner: int = Field(0, ge=0, le=5000)
    facility_id: Optional[UUID] = None
    is_opt_in: bool = False
    patient_ids: Optional[List[UUID]] = None
    group_ids: Optional[List[UUID]] = None


class ChallengeResponse(BaseModel):
    challenge_id: str
    title: str
    description: Optional[str] = None
    challenge_type: str
    scope: str
    metric_type: str
    target_value: float
    duration_days: int
    start_date: date
    end_date: date
    xp_reward: int
    bonus_xp_winner: int
    created_by_id: str
    created_by_type: str
    is_opt_in: bool
    is_active: bool
    participant_count: int = 0
    created_at: datetime
    avg_progress: float = 0.0
    top_participants: List[AvatarPreview] = []


class ChallengeParticipantResponse(BaseModel):
    participant_type: str
    participant_id: str
    participant_name: Optional[str] = None
    current_value: float
    status: str
    rank: Optional[int] = None
    xp_earned: int


class ChallengeDetailResponse(BaseModel):
    challenge: ChallengeResponse
    my_progress: Optional[ChallengeParticipantResponse] = None
    leaderboard: List[ChallengeParticipantResponse] = []


# ── Leaderboards ─────────────────────────────────────────────────────────────


class LeaderboardEntryResponse(BaseModel):
    rank: int
    patient_id: str
    patient_name: Optional[str] = None
    metric_value: float
    level: int
    title: str


class LeaderboardResponse(BaseModel):
    board_type: str
    board_scope: str
    period_start: date
    period_end: date
    entries: List[LeaderboardEntryResponse]
    my_rank: Optional[int] = None


# ── Activity Feed ────────────────────────────────────────────────────────────


class FeedEventResponse(BaseModel):
    feed_id: str
    actor_id: str
    actor_name: Optional[str] = None
    event_type: str
    event_data: Dict[str, Any] = {}
    cheer_count: int = 0
    my_cheer: Optional[str] = None
    created_at: datetime


class CheerInput(BaseModel):
    reaction: Reaction


# ── Weekly Quests ────────────────────────────────────────────────────────────


class WeeklyQuestResponse(BaseModel):
    quest_id: str
    week_start: date
    quest_type: str
    title: str
    description: Optional[str] = None
    target_value: float
    current_value: float
    xp_reward: int
    status: str
    progress_pct: float
    completed_at: Optional[datetime] = None


# ── Care Provider Views ──────────────────────────────────────────────────────


class PatientEngagementSummary(BaseModel):
    patient_id: str
    patient_name: Optional[str] = None
    level: int
    title: str
    total_xp: int
    current_streak: int
    last_active_date: Optional[date] = None
    tasks_completed_this_week: int = 0
    is_disengaged: bool = False


class CPGamificationOverview(BaseModel):
    total_patients: int
    active_patients: int
    disengaged_patients: int
    avg_streak: float = 0.0
    task_completion_pct: Optional[float] = None  # None when no tasks this week
    disengaged: List[PatientEngagementSummary] = []   # preview list, not the full count
    top_movers: List[PatientEngagementSummary] = []


LeaderboardMetric = Literal["streak", "xp", "weekly_xp", "monthly_xp", "weekly_steps"]


class CPLeaderboardEntry(BaseModel):
    rank: int
    patient_id: str
    patient_name: Optional[str] = None
    level: int
    title: str
    value: float


class CPLeaderboardResponse(BaseModel):
    metric: LeaderboardMetric
    total: int
    entries: List[CPLeaderboardEntry]


# ── XP History ───────────────────────────────────────────────────────────────


class XPHistoryEntry(BaseModel):
    date: date
    xp_earned: int
    tasks_completed: int


class XPHistoryResponse(BaseModel):
    period: str
    entries: List[XPHistoryEntry]
    total_xp_period: int


# ── Gamification Context (for AI agent) ──────────────────────────────────────


class GamificationContext(BaseModel):
    level: int
    title: str
    total_xp: int
    current_streak: int
    streak_multiplier: float
    streak_freezes: int
    recent_achievements: List[str] = []
    tasks_today: Dict[str, int] = {}
    # Titles of today's still-pending tasks — the nudges the patient will already
    # get today. The proactive brain reads these so it doesn't become a second
    # voice repeating a nudge already in flight.
    pending_task_titles: List[str] = []
    weekly_quest: Optional[Dict[str, Any]] = None
    active_challenges: List[Dict[str, Any]] = []
    buddy_streak: Optional[int] = None
