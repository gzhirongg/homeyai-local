"""Rename remaining_lease to remaining_lease_years (integer).

Revision ID: c9d0e1f2a3b4
Revises: b3c4d5e6f7a8
Create Date: 2026-05-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "hdb_resale_transactions",
        "remaining_lease",
        new_column_name="remaining_lease_years",
        existing_type=sa.String(),
        type_=sa.Integer(),
        postgresql_using="remaining_lease::integer",
        existing_nullable=True,
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "hdb_resale_transactions",
        "remaining_lease_years",
        new_column_name="remaining_lease",
        existing_type=sa.Integer(),
        type_=sa.String(),
        postgresql_using="remaining_lease_years::text",
        existing_nullable=True,
        nullable=True,
    )
