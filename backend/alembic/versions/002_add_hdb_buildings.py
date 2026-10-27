"""Add hdb_buildings PostGIS table.

Revision ID: 002_add_hdb_buildings
Revises: 001_baseline
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002_add_hdb_buildings"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.execute("""
        CREATE TABLE IF NOT EXISTS hdb_buildings (
            id          SERIAL PRIMARY KEY,
            objectid    INTEGER,
            blk_no      VARCHAR(20),
            st_cod      VARCHAR(20),
            entityid    INTEGER,
            postal_cod  VARCHAR(10),
            inc_crc     VARCHAR(20),
            fmel_upd_d  VARCHAR(20),
            shape_area  DOUBLE PRECISION,
            shape_len   DOUBLE PRECISION,
            geom        GEOMETRY(GEOMETRY, 4326)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_hdb_buildings_geom
        ON hdb_buildings USING GIST (geom)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_hdb_buildings_postal
        ON hdb_buildings (postal_cod)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_hdb_buildings_shape_area
        ON hdb_buildings (shape_area)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hdb_buildings")
