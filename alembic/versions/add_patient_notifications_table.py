"""Add patient_notifications table

Revision ID: add_patient_notifications_table
Revises: add_buddy_code_to_profiles
Create Date: 2026-04-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "add_patient_notifications_table"
down_revision: Union[str, None] = "add_buddy_code_to_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "patient_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=True),
        sa.Column("deeplink", sa.String(500), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.patient_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_patient_notifications_patient_created",
        "patient_notifications",
        ["patient_id", "created_at"],
    )
    op.create_index(
        "ix_patient_notifications_patient_unread",
        "patient_notifications",
        ["patient_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_patient_notifications_patient_unread",
        table_name="patient_notifications",
    )
    op.drop_index(
        "ix_patient_notifications_patient_created",
        table_name="patient_notifications",
    )
    op.drop_table("patient_notifications")
