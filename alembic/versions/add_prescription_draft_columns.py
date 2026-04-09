"""Add extracted_data, uploaded_by_id, uploaded_by_type to patient_prescriptions.

Supports draft prescription flow: patient/CP uploads → saved as draft with
extracted data → CP reviews and confirms.

Revision ID: add_prescription_draft_columns
Revises: add_medication_tables
Create Date: 2026-04-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "add_prescription_draft_columns"
down_revision: Union[str, None] = "add_medication_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "patient_prescriptions",
        sa.Column("extracted_data", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "patient_prescriptions",
        sa.Column("uploaded_by_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "patient_prescriptions",
        sa.Column("uploaded_by_type", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("patient_prescriptions", "uploaded_by_type")
    op.drop_column("patient_prescriptions", "uploaded_by_id")
    op.drop_column("patient_prescriptions", "extracted_data")
