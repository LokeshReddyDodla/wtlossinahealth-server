"""Redesign diet and fitness plan tables — drop old columns, add JSONB content

Revision ID: redesign_diet_fitness_plans
Revises: add_symptom_entries
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "redesign_diet_fitness_plans"
down_revision: Union[str, None] = "add_symptom_entries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Diet plans: drop old columns, add JSONB content ---
    op.drop_column("patient_diet_plans", "calcium")
    op.drop_column("patient_diet_plans", "iron")
    op.drop_column("patient_diet_plans", "zinc")
    op.drop_column("patient_diet_plans", "magnesium")
    op.drop_column("patient_diet_plans", "major_meal")
    op.drop_column("patient_diet_plans", "snack")
    op.add_column("patient_diet_plans", sa.Column("content", postgresql.JSONB(), nullable=True))

    # --- Fitness plans: drop old column, add JSONB content ---
    op.drop_column("patient_fitness_plans", "workout_plan")
    op.add_column("patient_fitness_plans", sa.Column("content", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    # --- Fitness plans: restore old column, drop content ---
    op.drop_column("patient_fitness_plans", "content")
    op.add_column("patient_fitness_plans", sa.Column("workout_plan", sa.String(), nullable=True))

    # --- Diet plans: restore old columns, drop content ---
    op.drop_column("patient_diet_plans", "content")
    op.add_column("patient_diet_plans", sa.Column("snack", postgresql.JSON(), nullable=True))
    op.add_column("patient_diet_plans", sa.Column("major_meal", postgresql.JSON(), nullable=True))
    op.add_column("patient_diet_plans", sa.Column("magnesium", sa.Float(), nullable=True))
    op.add_column("patient_diet_plans", sa.Column("zinc", sa.Float(), nullable=True))
    op.add_column("patient_diet_plans", sa.Column("iron", sa.Float(), nullable=True))
    op.add_column("patient_diet_plans", sa.Column("calcium", sa.Float(), nullable=True))
