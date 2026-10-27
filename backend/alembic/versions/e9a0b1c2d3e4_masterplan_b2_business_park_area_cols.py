"""Add B2 / business-park proximity scalars to masterplan snapshot.

Revision ID: e9a0b1c2d3e4
Revises: d4e3f2a1b9c8
Create Date: 2026-05-20

Computed offline from URA Master Plan Land Use GeoJSON (LU_DESC) distances and B2 ratio in 1 km disk.
Re-run ``build_masterplan_landuse_pit_snapshot.py --write-db`` after deploy to populate.

If a prior draft of this revision added ``area_industrial_b2_*`` / ``area_business_park_*`` columns,
manually drop those columns or run a one-off migration before applying this revision.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e9a0b1c2d3e4"
down_revision: Union[str, None] = "d4e3f2a1b9c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLS = (
    "dist_to_nearest_b2_zone",
    "b2_zoning_ratio_1km",
    "dist_to_nearest_business_park",
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
