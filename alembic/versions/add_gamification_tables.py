"""Add gamification tables (14 tables)

Revision ID: add_gamification_tables
Revises: redesign_diet_fitness_plans
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_gamification_tables"
down_revision: Union[str, None] = "redesign_diet_fitness_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. player_profiles ───────────────────────────────────────────────
    op.create_table(
        "player_profiles",
        sa.Column("player_profile_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_xp", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title_slug", sa.String(50), nullable=True),
        sa.Column("current_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("longest_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streak_freezes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("streak_resets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_active_date", sa.Date(), nullable=True),
        sa.Column("streak_frozen_on", sa.Date(), nullable=True),
        sa.Column("leaderboard_visibility", sa.String(20), nullable=False, server_default="group_only"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("patient_id", name="uq_player_profiles_patient_id"),
    )

    # ── 2. daily_tasks ───────────────────────────────────────────────────
    op.create_table(
        "daily_tasks",
        sa.Column("task_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_date", sa.Date(), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=True),
        sa.Column("current_value", sa.Float(), nullable=True, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("xp_reward", sa.Integer(), nullable=False),
        sa.Column("bonus_multiplier", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("patient_id", "task_date", "task_type", name="uq_daily_tasks_patient_date_type"),
    )
    op.create_index(
        "ix_daily_tasks_patient_date_status",
        "daily_tasks",
        ["patient_id", "task_date", "status"],
    )

    # ── 3. xp_ledger ────────────────────────────────────────────────────
    op.create_table(
        "xp_ledger",
        sa.Column("ledger_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("xp_amount", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_xp_ledger_patient_created",
        "xp_ledger",
        ["patient_id", "created_at"],
    )

    # ── 4. achievements ──────────────────────────────────────────────────
    op.create_table(
        "achievements",
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("icon", sa.String(100), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("xp_reward", sa.Integer(), nullable=False),
        sa.Column("criteria_type", sa.String(50), nullable=False),
        sa.Column("criteria_threshold", sa.Integer(), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_progressive", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("progressive_group", sa.String(80), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    # ── 5. patient_achievements ──────────────────────────────────────────
    op.create_table(
        "patient_achievements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("achievement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("earned_at", sa.DateTime(), nullable=False),
        sa.Column("notified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("starred_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("starred_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["achievement_id"], ["achievements.achievement_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["starred_by"], ["care_providers.care_provider_id"], ondelete="SET NULL"),
        sa.UniqueConstraint("patient_id", "achievement_id", name="uq_patient_achievements_patient_achievement"),
    )

    # ── 6. buddies ───────────────────────────────────────────────────────
    op.create_table(
        "buddies",
        sa.Column("buddy_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("buddy_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buddy_streak_longest", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_both_active", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("removed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["requester_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["accepter_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["removed_by"], ["patients.patient_id"], ondelete="SET NULL"),
        sa.UniqueConstraint("requester_id", "accepter_id", name="uq_buddies_requester_accepter"),
    )
    op.create_index("ix_buddies_requester_status", "buddies", ["requester_id", "status"])
    op.create_index("ix_buddies_accepter_status", "buddies", ["accepter_id", "status"])

    # ── 7. groups ────────────────────────────────────────────────────────
    op.create_table(
        "groups",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("group_type", sa.String(30), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_type", sa.String(20), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("max_members", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["facility_id"], ["health_facilities.health_facility_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_groups_facility_active", "groups", ["facility_id", "is_active"])
    op.create_index("ix_groups_created_by", "groups", ["created_by_id", "created_by_type"])

    # ── 8. group_members ─────────────────────────────────────────────────
    op.create_table(
        "group_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.Column("left_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.group_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "patient_id", name="uq_group_members_group_patient"),
    )
    op.create_index("ix_group_members_patient_active", "group_members", ["patient_id", "is_active"])
    op.create_index("ix_group_members_group_active", "group_members", ["group_id", "is_active"])

    # ── 9. challenges ────────────────────────────────────────────────────
    op.create_table(
        "challenges",
        sa.Column("challenge_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("challenge_type", sa.String(30), nullable=False),
        sa.Column("scope", sa.String(30), nullable=False),
        sa.Column("metric_type", sa.String(50), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("xp_reward", sa.Integer(), nullable=False),
        sa.Column("bonus_xp_winner", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_type", sa.String(20), nullable=False),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_opt_in", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["facility_id"], ["health_facilities.health_facility_id"], ondelete="SET NULL"),
    )
    op.create_index("ix_challenges_dates_active", "challenges", ["start_date", "end_date", "is_active"])
    op.create_index("ix_challenges_facility_active", "challenges", ["facility_id", "is_active"])
    op.create_index("ix_challenges_created_by", "challenges", ["created_by_id", "created_by_type"])

    # ── 10. challenge_participants ────────────────────────────────────────
    op.create_table(
        "challenge_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("challenge_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("participant_type", sa.String(20), nullable=False),
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("xp_earned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.challenge_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("challenge_id", "participant_type", "participant_id", name="uq_challenge_participants_challenge_type_id"),
    )
    op.create_index("ix_challenge_participants_challenge_status", "challenge_participants", ["challenge_id", "status"])
    op.create_index("ix_challenge_participants_participant", "challenge_participants", ["participant_id", "participant_type"])

    # ── 11. activity_feed ────────────────────────────────────────────────
    op.create_table(
        "activity_feed",
        sa.Column("feed_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("event_data", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("visibility", sa.String(20), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["groups.group_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_activity_feed_group_created", "activity_feed", ["group_id", "created_at"])
    op.create_index("ix_activity_feed_actor_created", "activity_feed", ["actor_id", "created_at"])
    op.create_index("ix_activity_feed_expires", "activity_feed", ["expires_at"])

    # ── 12. cheers ───────────────────────────────────────────────────────
    op.create_table(
        "cheers",
        sa.Column("cheer_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sender_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feed_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reaction", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["sender_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["feed_event_id"], ["activity_feed.feed_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("sender_id", "feed_event_id", name="uq_cheers_sender_event"),
    )
    op.create_index("ix_cheers_recipient_created", "cheers", ["recipient_id", "created_at"])
    op.create_index("ix_cheers_sender_created", "cheers", ["sender_id", "created_at"])

    # ── 13. leaderboard_entries ──────────────────────────────────────────
    op.create_table(
        "leaderboard_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("board_type", sa.String(30), nullable=False),
        sa.Column("board_scope", sa.String(30), nullable=False),
        sa.Column("scope_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_leaderboard_board_scope_period_rank",
        "leaderboard_entries",
        ["board_type", "board_scope", "scope_id", "period_start", "rank"],
    )
    op.create_index(
        "ix_leaderboard_patient_board",
        "leaderboard_entries",
        ["patient_id", "board_type"],
    )

    # ── 14. weekly_quests ────────────────────────────────────────────────
    op.create_table(
        "weekly_quests",
        sa.Column("quest_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("quest_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column("current_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("xp_reward", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("patient_id", "week_start", "quest_type", name="uq_weekly_quests_patient_week_type"),
    )
    op.create_index(
        "ix_weekly_quests_patient_week_status",
        "weekly_quests",
        ["patient_id", "week_start", "status"],
    )

    # ── Seed achievement catalog ─────────────────────────────────────────
    import uuid
    # Deterministic UUIDs: same slug → same UUID across all environments
    ACHIEVEMENT_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    from lib.services.gamification.achievement_catalog import ACHIEVEMENT_CATALOG

    achievements_table = sa.table(
        "achievements",
        sa.column("achievement_id", postgresql.UUID(as_uuid=True)),
        sa.column("slug", sa.String),
        sa.column("title", sa.String),
        sa.column("description", sa.String),
        sa.column("icon", sa.String),
        sa.column("category", sa.String),
        sa.column("tier", sa.String),
        sa.column("xp_reward", sa.Integer),
        sa.column("criteria_type", sa.String),
        sa.column("criteria_threshold", sa.Integer),
        sa.column("is_hidden", sa.Boolean),
        sa.column("is_progressive", sa.Boolean),
        sa.column("progressive_group", sa.String),
        sa.column("sort_order", sa.Integer),
    )

    rows = [
        {
            "achievement_id": uuid.uuid5(ACHIEVEMENT_NAMESPACE, a["slug"]),
            "slug": a["slug"],
            "title": a["title"],
            "description": a["description"],
            "icon": a["icon"],
            "category": a["category"],
            "tier": a["tier"],
            "xp_reward": a["xp_reward"],
            "criteria_type": a["criteria_type"],
            "criteria_threshold": a["criteria_threshold"],
            "is_hidden": a.get("is_hidden", False),
            "is_progressive": a.get("is_progressive", False),
            "progressive_group": a.get("progressive_group"),
            "sort_order": a.get("sort_order", 0),
        }
        for a in ACHIEVEMENT_CATALOG
    ]
    op.bulk_insert(achievements_table, rows)


def downgrade() -> None:
    op.drop_table("weekly_quests")
    op.drop_table("leaderboard_entries")
    op.drop_table("cheers")
    op.drop_table("activity_feed")
    op.drop_table("challenge_participants")
    op.drop_table("challenges")
    op.drop_table("group_members")
    op.drop_table("groups")
    op.drop_table("buddies")
    op.drop_table("patient_achievements")
    op.drop_table("achievements")
    op.drop_table("xp_ledger")
    op.drop_table("daily_tasks")
    op.drop_table("player_profiles")
