"""Add mrt_station_exits PostGIS table.

Revision ID: 003_add_mrt_station_exits
Revises: 002_add_hdb_buildings
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "003_add_mrt_station_exits"
down_revision: Union[str, None] = "002_add_hdb_buildings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.execute("""
        CREATE TABLE IF NOT EXISTS mrt_station_exits (
            id           SERIAL PRIMARY KEY,
            objectid     INTEGER,
            station_name VARCHAR(100),
            exit_code    VARCHAR(20),
            inc_crc      VARCHAR(20),
            fmel_upd_d   VARCHAR(20),
            geom         GEOMETRY(POINT, 4326)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrt_station_exits_geom
        ON mrt_station_exits USING GIST (geom)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_mrt_station_exits_name
        ON mrt_station_exits (station_name)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mrt_station_exits")
