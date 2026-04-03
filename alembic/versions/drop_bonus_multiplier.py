"""Drop unused bonus_multiplier column from daily_tasks

Revision ID: drop_bonus_multiplier
Revises: add_gamification_tables
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "drop_bonus_multiplier"
down_revision: Union[str, None] = "add_gamification_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("daily_tasks", "bonus_multiplier")


def downgrade() -> None:
    op.add_column("daily_tasks", sa.Column("bonus_multiplier", sa.Float(), nullable=False, server_default="1.0"))
