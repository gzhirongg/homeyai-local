"""Add analysis_reports table for the reports repository feature.

Revision ID: 004_add_analysis_reports
Revises: 003_add_mrt_station_exits
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_add_analysis_reports"
down_revision: Union[str, None] = "003_add_mrt_station_exits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filter_state", sa.Text(), nullable=False),
        sa.Column("ai_commentary", sa.Text(), nullable=True),
        sa.Column("chart_config", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_analysis_reports_id", "analysis_reports", ["id"])
    op.create_index("ix_analysis_reports_user_id", "analysis_reports", ["user_id"])


def downgrade() -> None:
    op.drop_table("analysis_reports")
