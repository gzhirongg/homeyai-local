"""masterplan land use PIT: revision catalog + normalized scalars

Revision ID: b3c4d5e6f7a8
Revises: 008_add_property_nickname
Create Date: 2026-05-16
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "008_add_property_nickname"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS masterplan_revision_catalog (
            revision_year  SMALLINT     NOT NULL,
            effective_from VARCHAR(7)   NOT NULL,
            minio_key      TEXT         NOT NULL,
            PRIMARY KEY (revision_year)
        );

        CREATE TABLE IF NOT EXISTS masterplan_landuse_pit_scalars (
            enriched_addr_id          INTEGER   NOT NULL,
            revision_year             SMALLINT  NOT NULL,
            nearby_high_density_score DOUBLE PRECISION,
            area_comm_500m            DOUBLE PRECISION,
            area_comm_1000m           DOUBLE PRECISION,
            area_comm_1500m           DOUBLE PRECISION,
            area_park_500m            DOUBLE PRECISION,
            area_park_1000m           DOUBLE PRECISION,
            area_park_1500m           DOUBLE PRECISION,
            area_sports_500m          DOUBLE PRECISION,
            area_sports_1000m         DOUBLE PRECISION,
            area_sports_1500m         DOUBLE PRECISION,
            area_health_500m          DOUBLE PRECISION,
            area_health_1000m         DOUBLE PRECISION,
            area_health_1500m         DOUBLE PRECISION,
            area_worship_500m         DOUBLE PRECISION,
            area_worship_1000m        DOUBLE PRECISION,
            area_worship_1500m        DOUBLE PRECISION,
            dist_cbd                  DOUBLE PRECISION,
            dist_airport              DOUBLE PRECISION,
            computed_at               TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (enriched_addr_id, revision_year),
            CONSTRAINT fk_masterplan_scalars_revision_year
                FOREIGN KEY (revision_year)
                REFERENCES masterplan_revision_catalog (revision_year)
        );
        CREATE INDEX IF NOT EXISTS idx_masterplan_scalars_revision
            ON masterplan_landuse_pit_scalars (revision_year);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS masterplan_landuse_pit_scalars;")
    op.execute("DROP TABLE IF EXISTS masterplan_revision_catalog;")
