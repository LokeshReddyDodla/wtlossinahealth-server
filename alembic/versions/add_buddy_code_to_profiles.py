"""Add buddy_code to player_profiles table

Revision ID: add_buddy_code_to_profiles
Revises: add_group_invite_code
Create Date: 2026-04-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_buddy_code_to_profiles"
down_revision: Union[str, None] = "add_group_invite_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "player_profiles",
        sa.Column("buddy_code", sa.String(8), nullable=True),
    )
    op.create_index(
        "ix_player_profiles_buddy_code",
        "player_profiles",
        ["buddy_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_player_profiles_buddy_code", table_name="player_profiles")
    op.drop_column("player_profiles", "buddy_code")
