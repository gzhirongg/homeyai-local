"""Add cemetery and special-use proximity scalars to masterplan snapshot.

Revision ID: f1a2b3c4d5e7
Revises: e9a0b1c2d3e4
Create Date: 2026-05-20

Re-run ``build_masterplan_landuse_pit_snapshot.py --write-db`` after deploy to populate.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f1a2b3c4d5e7"
down_revision: Union[str, None] = "e9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLS = (
    "dist_to_nearest_cemetery",
    "dist_to_nearest_special_use",
)


def upgrade() -> None:
    for col in _NEW_COLS:
        op.execute(
            f"ALTER TABLE masterplan_landuse_pit_scalars "
            f"ADD COLUMN IF NOT EXISTS {col} DOUBLE PRECISION;"
        )


def downgrade() -> None:
    for col in _NEW_COLS:
        op.execute(f"ALTER TABLE masterplan_landuse_pit_scalars DROP COLUMN IF EXISTS {col};")
