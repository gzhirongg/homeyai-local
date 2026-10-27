"""add_mrt_stations_temporal

Revision ID: a0846ab829e0
Revises: 6612ced7527e
Create Date: 2026-04-19 18:12:36.722844
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0846ab829e0'
down_revision: Union[str, None] = '6612ced7527e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE mrt_stations_temporal (
            id SERIAL PRIMARY KEY,
            network_line VARCHAR(255),
            subproject_or_stage VARCHAR(255),
            station_code VARCHAR(50),
            station_name VARCHAR(255),
            station_status VARCHAR(50),
            working_name_flag VARCHAR(50),
            code_source_type VARCHAR(100),
            announcement_date_raw VARCHAR(255),
            announcement_date DATE,
            expected_completion_raw VARCHAR(255),
            expected_completion DATE,
            opening_date_raw VARCHAR(255),
            opening_date DATE,
            dates_source_type VARCHAR(100),
            phase2_review_priority VARCHAR(50),
            source_url TEXT,
            source_note TEXT,
            lat DOUBLE PRECISION,
            long DOUBLE PRECISION,
            search_term VARCHAR(255),
            found INTEGER,
            api_response TEXT,
            geom GEOMETRY(POINT, 4326)
        )
    """)
    op.execute("CREATE INDEX idx_mrt_stations_temporal_geom ON mrt_stations_temporal USING GIST (geom)")
    op.execute("CREATE INDEX idx_mrt_stations_temporal_name ON mrt_stations_temporal (station_name)")
    
    op.execute("DROP TABLE IF EXISTS mrt_station_exits")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mrt_stations_temporal")

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
