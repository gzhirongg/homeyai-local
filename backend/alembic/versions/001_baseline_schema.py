"""Baseline schema — captures existing tables as of initial Alembic setup.

Revision ID: 001_baseline
Revises: None
Create Date: 2026-03-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("remaining_valuations", sa.Integer(), nullable=True),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "saved_properties",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("postal_code", sa.String(), nullable=True),
        sa.Column("property_type", sa.String(), nullable=True),
        sa.Column("predicted_price", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=True),
    )
    op.create_index("ix_saved_properties_id", "saved_properties", ["id"])
    op.create_index("ix_saved_properties_user_id", "saved_properties", ["user_id"])

    op.create_table(
        "hdb_resale_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("month", sa.String(), nullable=True),
        sa.Column("town", sa.String(), nullable=True),
        sa.Column("flat_type", sa.String(), nullable=True),
        sa.Column("block", sa.String(), nullable=True),
        sa.Column("street_name", sa.String(), nullable=True),
        sa.Column("storey_range", sa.String(), nullable=True),
        sa.Column("floor_area_sqm", sa.Integer(), nullable=True),
        sa.Column("flat_model", sa.String(), nullable=True),
        sa.Column("lease_commence_date", sa.Integer(), nullable=True),
        sa.Column("remaining_lease", sa.String(), nullable=True),
        sa.Column("resale_price", sa.Integer(), nullable=True),
    )
    op.create_index("ix_hdb_resale_transactions_id", "hdb_resale_transactions", ["id"])
    op.create_index("ix_hdb_resale_transactions_month", "hdb_resale_transactions", ["month"])
    op.create_index("ix_hdb_resale_transactions_town", "hdb_resale_transactions", ["town"])


def downgrade() -> None:
    op.drop_table("hdb_resale_transactions")
    op.drop_table("saved_properties")
    op.drop_table("users")
