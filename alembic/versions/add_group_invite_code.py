"""Add invite_code to groups table

Revision ID: add_group_invite_code
Revises: drop_bonus_multiplier
Create Date: 2026-04-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "add_group_invite_code"
down_revision: Union[str, None] = "drop_bonus_multiplier"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "groups",
        sa.Column("invite_code", sa.String(8), nullable=True),
    )
    op.create_index("ix_groups_invite_code", "groups", ["invite_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_groups_invite_code", table_name="groups")
    op.drop_column("groups", "invite_code")
