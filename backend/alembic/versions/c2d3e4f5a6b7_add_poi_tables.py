"""Add poi_locations and hdb_poi_features for POI ingestion and pre-computed address features.

Revision ID: c2d3e4f5a6b7
Revises: b2c3d4e5f6a7
Create Date: 2026-05-13

"""

from typing import Sequence, Union

from alembic import op


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS poi_locations (
            id SERIAL PRIMARY KEY,
            poi_type VARCHAR(32) NOT NULL,
            name TEXT,
            lat DOUBLE PRECISION NOT NULL,
            lon DOUBLE PRECISION NOT NULL,
            valid_from DATE,
            valid_to DATE,
            source_file VARCHAR(128) NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_poi_locations_type
        ON poi_locations (poi_type);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_poi_locations_geom
        ON poi_locations USING GIST (ST_SetSRID(ST_MakePoint(lon, lat), 4326));
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hdb_poi_features (
            hdb_addr_id INTEGER NOT NULL PRIMARY KEY
                REFERENCES hdb_address_enrichment_onemap(id) ON DELETE CASCADE,
            dist_cbd REAL,
            dist_airport REAL,
            dist_nearest_top20_school REAL,
            dist_nearest_any_school REAL,
            within_1km_top20_school SMALLINT,
            within_1km_2km_top20_school SMALLINT,
            within_1km_any_pri_school SMALLINT,
            within_1km_2km_pri_school SMALLINT,
            dist_nearest_mall REAL,
            malls_within_2km SMALLINT,
            supermarkets_within_500m SMALLINT,
            markets_within_500m SMALLINT,
            dist_nearest_park REAL,
            is_park_200m SMALLINT,
            dist_nearest_pcn REAL,
            gravity_malls REAL,
            gravity_schools REAL,
            gravity_parks REAL,
            gravity_markets REAL,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_training_readonly') THEN
                GRANT SELECT ON TABLE public.poi_locations TO ml_training_readonly;
                GRANT SELECT ON TABLE public.hdb_poi_features TO ml_training_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hdb_poi_features")
    op.execute("DROP TABLE IF EXISTS poi_locations")
