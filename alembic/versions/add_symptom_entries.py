"""Add symptom_entries and symptom_entry_items tables

Revision ID: add_symptom_entries
Revises: add_sleep_checkins_and_mood_entries
Create Date: 2026-04-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_symptom_entries"
down_revision: Union[str, None] = "add_sleep_checkins_and_mood_entries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- symptom_entries (parent) ---
    op.create_table(
        "symptom_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.patient_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_symptom_entries_patient_recorded", "symptom_entries", ["patient_id", "recorded_at"])
    op.create_index("ix_symptom_entries_patient_created", "symptom_entries", ["patient_id", "created_at"])

    # --- symptom_entry_items (child) ---
    op.create_table(
        "symptom_entry_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symptom_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symptom_name", sa.String(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("custom_label", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["symptom_entry_id"], ["symptom_entries.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_symptom_entry_items_entry", "symptom_entry_items", ["symptom_entry_id"])
    op.create_index("ix_symptom_entry_items_name", "symptom_entry_items", ["symptom_name"])


def downgrade() -> None:
    op.drop_index("ix_symptom_entry_items_name", table_name="symptom_entry_items")
    op.drop_index("ix_symptom_entry_items_entry", table_name="symptom_entry_items")
    op.drop_table("symptom_entry_items")

    op.drop_index("ix_symptom_entries_patient_created", table_name="symptom_entries")
    op.drop_index("ix_symptom_entries_patient_recorded", table_name="symptom_entries")
    op.drop_table("symptom_entries")
