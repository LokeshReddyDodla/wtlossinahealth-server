import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import relationship

from lib.models import Base


def _now():
    return datetime.now().replace(tzinfo=None)


# ── Table 1: Player Profiles ────────────────────────────────────────────────


class PlayerProfile(Base):
    __tablename__ = "player_profiles"

    player_profile_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    total_xp = Column(BigInteger, default=0, nullable=False)
    level = Column(Integer, default=1, nullable=False)
    title_slug = Column(String(50), nullable=True)
    current_streak = Column(Integer, default=0, nullable=False)
    longest_streak = Column(Integer, default=0, nullable=False)
    streak_freezes = Column(Integer, default=1, nullable=False)
    streak_resets = Column(Integer, default=0, nullable=False)
    last_active_date = Column(Date, nullable=True)
    streak_frozen_on = Column(Date, nullable=True)
    buddy_code = Column(String(8), unique=True, nullable=True)
    leaderboard_visibility = Column(
        String(20), default="group_only", nullable=False
    )
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    patient = relationship("Patient", back_populates="player_profile")


# ── Table 2: Daily Tasks ────────────────────────────────────────────────────


class DailyTask(Base):
    __tablename__ = "daily_tasks"
    __table_args__ = (
        UniqueConstraint(
            "patient_id", "task_date", "task_type",
            name="uq_daily_tasks_patient_date_type",
        ),
        Index(
            "ix_daily_tasks_patient_date_status",
            "patient_id", "task_date", "status",
        ),
    )

    task_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    task_date = Column(Date, nullable=False)
    task_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    source_type = Column(String(30), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=True)
    target_value = Column(Float, nullable=True)
    current_value = Column(Float, default=0, nullable=True)
    status = Column(String(20), default="pending", nullable=False)
    xp_reward = Column(Integer, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)

    patient = relationship("Patient", back_populates="daily_tasks")


# ── Table 3: XP Ledger ──────────────────────────────────────────────────────


class XPLedgerEntry(Base):
    __tablename__ = "xp_ledger"
    __table_args__ = (
        Index("ix_xp_ledger_patient_created", "patient_id", "created_at"),
    )

    ledger_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    xp_amount = Column(Integer, nullable=False)
    source_type = Column(String(50), nullable=False)
    source_id = Column(UUID(as_uuid=True), nullable=True)
    description = Column(String(300), nullable=False)
    created_at = Column(DateTime, default=_now)

    patient = relationship("Patient")


# ── Table 4: Achievements (definition, seeded) ──────────────────────────────


class Achievement(Base):
    __tablename__ = "achievements"

    achievement_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug = Column(String(80), unique=True, nullable=False)
    title = Column(String(150), nullable=False)
    description = Column(String(500), nullable=False)
    icon = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    tier = Column(String(20), nullable=False)
    xp_reward = Column(Integer, nullable=False)
    criteria_type = Column(String(50), nullable=False)
    criteria_threshold = Column(Integer, nullable=False)
    is_hidden = Column(Boolean, default=False, nullable=False)
    is_progressive = Column(Boolean, default=False, nullable=False)
    progressive_group = Column(String(80), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=_now)


# ── Table 5: Patient Achievements ────────────────────────────────────────────


class PatientAchievement(Base):
    __tablename__ = "patient_achievements"
    __table_args__ = (
        UniqueConstraint(
            "patient_id", "achievement_id",
            name="uq_patient_achievements_patient_achievement",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    achievement_id = Column(
        UUID(as_uuid=True),
        ForeignKey("achievements.achievement_id", ondelete="CASCADE"),
        nullable=False,
    )
    earned_at = Column(DateTime, nullable=False, default=_now)
    notified = Column(Boolean, default=False, nullable=False)
    starred_by = Column(
        UUID(as_uuid=True),
        ForeignKey("care_providers.care_provider_id", ondelete="SET NULL"),
        nullable=True,
    )
    starred_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="achievements")
    achievement = relationship("Achievement")


# ── Table 6: Buddies ─────────────────────────────────────────────────────────


class Buddy(Base):
    __tablename__ = "buddies"
    __table_args__ = (
        UniqueConstraint(
            "requester_id", "accepter_id",
            name="uq_buddies_requester_accepter",
        ),
        Index("ix_buddies_requester_status", "requester_id", "status"),
        Index("ix_buddies_accepter_status", "accepter_id", "status"),
    )

    buddy_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    requester_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    accepter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(20), default="pending", nullable=False)
    buddy_streak = Column(Integer, default=0, nullable=False)
    buddy_streak_longest = Column(Integer, default=0, nullable=False)
    last_both_active = Column(Date, nullable=True)
    created_at = Column(DateTime, default=_now)
    accepted_at = Column(DateTime, nullable=True)
    removed_at = Column(DateTime, nullable=True)
    removed_by = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="SET NULL"),
        nullable=True,
    )

    requester = relationship(
        "Patient", foreign_keys=[requester_id], backref="buddy_requests_sent"
    )
    accepter = relationship(
        "Patient", foreign_keys=[accepter_id], backref="buddy_requests_received"
    )


# ── Table 7: Groups ─────────────────────────────────────────────────────────


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (
        Index("ix_groups_facility_active", "facility_id", "is_active"),
        Index(
            "ix_groups_created_by",
            "created_by_id", "created_by_type",
        ),
    )

    group_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    group_type = Column(String(30), nullable=False)
    created_by_id = Column(UUID(as_uuid=True), nullable=False)
    created_by_type = Column(String(20), nullable=False)
    facility_id = Column(
        UUID(as_uuid=True),
        ForeignKey("health_facilities.health_facility_id", ondelete="SET NULL"),
        nullable=True,
    )
    avatar_url = Column(String(500), nullable=True)
    # Short shareable code so patients can invite others (e.g. "AHX392").
    # Generated on creation; unique so it can be used as a join key.
    invite_code = Column(String(8), nullable=True, unique=True, index=True)
    max_members = Column(Integer, default=50, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    facility = relationship("HealthFacility")
    members = relationship(
        "GroupMember", back_populates="group", cascade="all, delete-orphan"
    )


# ── Table 8: Group Members ──────────────────────────────────────────────────


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "patient_id",
            name="uq_group_members_group_patient",
        ),
        Index("ix_group_members_patient_active", "patient_id", "is_active"),
        Index("ix_group_members_group_active", "group_id", "is_active"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("groups.group_id", ondelete="CASCADE"),
        nullable=False,
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    role = Column(String(20), default="member", nullable=False)
    joined_at = Column(DateTime, default=_now)
    left_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    group = relationship("Group", back_populates="members")
    patient = relationship("Patient")


# ── Table 9: Challenges ──────────────────────────────────────────────────────


class Challenge(Base):
    __tablename__ = "challenges"
    __table_args__ = (
        Index(
            "ix_challenges_dates_active",
            "start_date", "end_date", "is_active",
        ),
        Index("ix_challenges_facility_active", "facility_id", "is_active"),
        Index(
            "ix_challenges_created_by",
            "created_by_id", "created_by_type",
        ),
    )

    challenge_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title = Column(String(200), nullable=False)
    description = Column(String(1000), nullable=True)
    challenge_type = Column(String(30), nullable=False)
    scope = Column(String(30), nullable=False)
    metric_type = Column(String(50), nullable=False)
    target_value = Column(Float, nullable=False)
    duration_days = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    xp_reward = Column(Integer, nullable=False)
    bonus_xp_winner = Column(Integer, default=0, nullable=False)
    created_by_id = Column(UUID(as_uuid=True), nullable=False)
    created_by_type = Column(String(20), nullable=False)
    facility_id = Column(
        UUID(as_uuid=True),
        ForeignKey("health_facilities.health_facility_id", ondelete="SET NULL"),
        nullable=True,
    )
    is_opt_in = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    facility = relationship("HealthFacility")
    participants = relationship(
        "ChallengeParticipant",
        back_populates="challenge",
        cascade="all, delete-orphan",
    )


# ── Table 10: Challenge Participants ─────────────────────────────────────────


class ChallengeParticipant(Base):
    __tablename__ = "challenge_participants"
    __table_args__ = (
        UniqueConstraint(
            "challenge_id", "participant_type", "participant_id",
            name="uq_challenge_participants_challenge_type_id",
        ),
        Index(
            "ix_challenge_participants_challenge_status",
            "challenge_id", "status",
        ),
        Index(
            "ix_challenge_participants_participant",
            "participant_id", "participant_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    challenge_id = Column(
        UUID(as_uuid=True),
        ForeignKey("challenges.challenge_id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_type = Column(String(20), nullable=False)
    participant_id = Column(UUID(as_uuid=True), nullable=False)
    current_value = Column(Float, default=0, nullable=False)
    status = Column(String(20), default="active", nullable=False)
    rank = Column(Integer, nullable=True)
    xp_earned = Column(Integer, default=0, nullable=False)
    joined_at = Column(DateTime, default=_now)
    completed_at = Column(DateTime, nullable=True)

    challenge = relationship("Challenge", back_populates="participants")


# ── Table 11: Activity Feed ──────────────────────────────────────────────────


class ActivityFeedEvent(Base):
    __tablename__ = "activity_feed"
    __table_args__ = (
        Index(
            "ix_activity_feed_group_created",
            "group_id", "created_at",
        ),
        Index(
            "ix_activity_feed_actor_created",
            "actor_id", "created_at",
        ),
        Index("ix_activity_feed_expires", "expires_at"),
    )

    feed_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(String(50), nullable=False)
    event_data = Column(JSON, nullable=False, default=dict)
    visibility = Column(String(20), nullable=False)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("groups.group_id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at = Column(DateTime, default=_now)
    expires_at = Column(DateTime, nullable=False)

    actor = relationship("Patient")
    group = relationship("Group")
    cheers = relationship(
        "Cheer", back_populates="feed_event", cascade="all, delete-orphan"
    )


# ── Table 12: Cheers ─────────────────────────────────────────────────────────


class Cheer(Base):
    __tablename__ = "cheers"
    __table_args__ = (
        UniqueConstraint(
            "sender_id", "feed_event_id",
            name="uq_cheers_sender_event",
        ),
        Index("ix_cheers_recipient_created", "recipient_id", "created_at"),
        Index("ix_cheers_sender_created", "sender_id", "created_at"),
    )

    cheer_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sender_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    feed_event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("activity_feed.feed_id", ondelete="CASCADE"),
        nullable=False,
    )
    reaction = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=_now)

    sender = relationship("Patient", foreign_keys=[sender_id])
    recipient = relationship("Patient", foreign_keys=[recipient_id])
    feed_event = relationship("ActivityFeedEvent", back_populates="cheers")


# ── Table 13: Leaderboard Entries (materialized) ─────────────────────────────


class LeaderboardEntry(Base):
    __tablename__ = "leaderboard_entries"
    __table_args__ = (
        Index(
            "ix_leaderboard_board_scope_period_rank",
            "board_type", "board_scope", "scope_id", "period_start", "rank",
        ),
        Index(
            "ix_leaderboard_patient_board",
            "patient_id", "board_type",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    board_type = Column(String(30), nullable=False)
    board_scope = Column(String(30), nullable=False)
    scope_id = Column(UUID(as_uuid=True), nullable=True)
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    rank = Column(Integer, nullable=False)
    metric_value = Column(Float, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    computed_at = Column(DateTime, default=_now)

    patient = relationship("Patient")


# ── Table 14: Weekly Quests ──────────────────────────────────────────────────


class WeeklyQuest(Base):
    __tablename__ = "weekly_quests"
    __table_args__ = (
        UniqueConstraint(
            "patient_id", "week_start", "quest_type",
            name="uq_weekly_quests_patient_week_type",
        ),
        Index(
            "ix_weekly_quests_patient_week_status",
            "patient_id", "week_start", "status",
        ),
    )

    quest_id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    patient_id = Column(
        UUID(as_uuid=True),
        ForeignKey("patients.patient_id", ondelete="CASCADE"),
        nullable=False,
    )
    week_start = Column(Date, nullable=False)
    quest_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(String(500), nullable=True)
    target_value = Column(Float, nullable=False)
    current_value = Column(Float, default=0, nullable=False)
    xp_reward = Column(Integer, nullable=False)
    status = Column(String(20), default="active", nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)

    patient = relationship("Patient", back_populates="weekly_quests")
