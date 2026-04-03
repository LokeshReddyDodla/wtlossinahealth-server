"""Drop patient_vitals table — vitals now stored in ClickHouse

Revision ID: drop_patient_vitals_table
Revises: add_agent_meal_v1_tables
Create Date: 2026-04-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "drop_patient_vitals_table"
down_revision: Union[str, None] = "add_agent_meal_v1_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("patient_vitals")


def downgrade() -> None:
    op.create_table(
        "patient_vitals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.patient_id"), nullable=False),
        sa.Column("a1c", sa.Float, nullable=True),
        sa.Column("creatinine", sa.Float, nullable=True),
        sa.Column("diastolic_bp", sa.Float, nullable=True),
        sa.Column("systolic_bp", sa.Float, nullable=True),
        sa.Column("heart_rate", sa.Float, nullable=True),
        sa.Column("ketones", sa.Float, nullable=True),
        sa.Column("respiratory_rate", sa.Float, nullable=True),
        sa.Column("spo2", sa.Float, nullable=True),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("weight", sa.Float, nullable=True),
        sa.Column("test_time", sa.DateTime, nullable=False),
        sa.Column("uploaded_at", sa.DateTime, nullable=True),
        sa.Column("source_name", sa.String, nullable=False),
        sa.Column("source_platform", sa.String, nullable=False),
    )
