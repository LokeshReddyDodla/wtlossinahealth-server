"""Rename old prescription/medication tables to *_legacy, create new clean tables.

Revision ID: add_medication_tables
Revises: redesign_diet_fitness_plans
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_medication_tables"
down_revision: Union[str, None] = "f1cef9197757"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Rename old tables to *_legacy ────────────────────────────────────

    # Must rename child table first (FK references parent)
    op.rename_table("patient_prescription_medicines", "patient_prescription_medicines_legacy")
    op.rename_table("patient_prescriptions", "patient_prescriptions_legacy")
    op.rename_table("patient_current_medication", "patient_current_medications_legacy")

    # Update FK on legacy child table to point to renamed parent
    op.drop_constraint(
        "patient_prescription_medicines_prescription_id_fkey",
        "patient_prescription_medicines_legacy",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "patient_prescription_medicines_legacy_prescription_id_fkey",
        "patient_prescription_medicines_legacy",
        "patient_prescriptions_legacy",
        ["prescription_id"],
        ["prescription_id"],
        ondelete="CASCADE",
    )

    # ── Create new patient_prescriptions ─────────────────────────────────

    op.create_table(
        "patient_prescriptions",
        sa.Column("prescription_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("patients.patient_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("doctor_name", sa.String, nullable=True),
        sa.Column("prescription_date", sa.Date, nullable=True),
        sa.Column("file_urls", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String, nullable=False, server_default="draft"),
        sa.Column("follow_up_required", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("follow_up_date", sa.Date, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_prescription_patient_status",
        "patient_prescriptions",
        ["patient_id", "status"],
    )

    # ── Create new patient_medications ───────────────────────────────────

    op.create_table(
        "patient_medications",
        sa.Column("medication_id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "patient_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("patients.patient_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prescription_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("patient_prescriptions.prescription_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("brand_name", sa.String, nullable=True),
        sa.Column("strength", sa.String, nullable=True),
        sa.Column("formulation", sa.String, nullable=True),
        sa.Column("route", sa.String, nullable=True),
        sa.Column("food_timing", sa.String, nullable=True),
        sa.Column("doses", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("purpose", sa.String, nullable=True),
        sa.Column("instructions", sa.Text, nullable=True),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("status", sa.String, nullable=False, server_default="active"),
        sa.Column("discontinued_at", sa.DateTime, nullable=True),
        sa.Column("discontinued_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_medication_patient_status",
        "patient_medications",
        ["patient_id", "status"],
    )
    op.create_index(
        "ix_medication_patient_end",
        "patient_medications",
        ["patient_id", "end_date"],
    )


def downgrade() -> None:
    op.drop_table("patient_medications")
    op.drop_table("patient_prescriptions")

    # Restore FK on legacy child table
    op.drop_constraint(
        "patient_prescription_medicines_legacy_prescription_id_fkey",
        "patient_prescription_medicines_legacy",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "patient_prescription_medicines_prescription_id_fkey",
        "patient_prescription_medicines_legacy",
        "patient_prescriptions_legacy",
        ["prescription_id"],
        ["prescription_id"],
        ondelete="CASCADE",
    )

    op.rename_table("patient_current_medications_legacy", "patient_current_medication")
    op.rename_table("patient_prescriptions_legacy", "patient_prescriptions")
    op.rename_table("patient_prescription_medicines_legacy", "patient_prescription_medicines")
