"""drop cycle columns from hdb_mrt_routes

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-11

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("hdb_mrt_routes", "raw_cycle_response")
    op.drop_column("hdb_mrt_routes", "cycle_time_mins")
    op.drop_column("hdb_mrt_routes", "cycle_distance_m")


def downgrade() -> None:
    op.add_column(
        "hdb_mrt_routes",
        sa.Column("cycle_distance_m", sa.Integer(), nullable=True),
    )
    op.add_column(
        "hdb_mrt_routes",
        sa.Column("cycle_time_mins", sa.Integer(), nullable=True),
    )
    op.add_column(
        "hdb_mrt_routes",
        sa.Column("raw_cycle_response", sa.Text(), nullable=True),
    )
