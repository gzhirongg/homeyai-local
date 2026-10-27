"""Add hdb_property_information (HDB Property Information catalogue)."""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "a8f7e6d5c4b3"
down_revision: Union[str, None] = "fef1c8d93a41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if not inspect(conn).has_table("hdb_property_information"):
        op.execute(
            """
            CREATE TABLE hdb_property_information (
                id                      SERIAL PRIMARY KEY,
                blk_street              TEXT NOT NULL,
                enriched_addr_id        INTEGER,
                blk_no                  TEXT NOT NULL,
                street                  TEXT NOT NULL,
                street_norm             TEXT NOT NULL,
                max_floor_lvl           SMALLINT,
                year_completed          SMALLINT NOT NULL,
                residential             BOOLEAN NOT NULL,
                commercial              BOOLEAN NOT NULL,
                market_hawker           BOOLEAN NOT NULL,
                miscellaneous           BOOLEAN NOT NULL,
                multistorey_carpark     BOOLEAN NOT NULL,
                precinct_pavilion       BOOLEAN NOT NULL,
                bldg_contract_town      CHAR(3) NOT NULL,
                hdb_town                TEXT NOT NULL,
                total_dwelling_units    INTEGER NOT NULL DEFAULT 0,
                room_1_sold             INTEGER NOT NULL DEFAULT 0,
                room_2_sold             INTEGER NOT NULL DEFAULT 0,
                room_3_sold             INTEGER NOT NULL DEFAULT 0,
                room_4_sold             INTEGER NOT NULL DEFAULT 0,
                room_5_sold             INTEGER NOT NULL DEFAULT 0,
                exec_sold               INTEGER NOT NULL DEFAULT 0,
                multigen_sold           INTEGER NOT NULL DEFAULT 0,
                studio_apartment_sold   INTEGER NOT NULL DEFAULT 0,
                room_1_rental           INTEGER NOT NULL DEFAULT 0,
                room_2_rental           INTEGER NOT NULL DEFAULT 0,
                room_3_rental           INTEGER NOT NULL DEFAULT 0,
                other_room_rental       INTEGER NOT NULL DEFAULT 0,
                source                  TEXT NOT NULL DEFAULT 'data.gov.sg',
                source_resource_id      TEXT NOT NULL DEFAULT 'd_17f5382f26140b1fdae0ba2ef6239d2f',
                ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT uq_hdb_property_blk_street UNIQUE (blk_street),
                CONSTRAINT fk_hdb_property_enriched_addr
                    FOREIGN KEY (enriched_addr_id)
                    REFERENCES hdb_address_enrichment_onemap (id)
                    ON DELETE SET NULL,
                CONSTRAINT chk_hdb_property_year
                    CHECK (year_completed BETWEEN 1937 AND 2100),
                CONSTRAINT chk_hdb_property_dwelling_nonneg
                    CHECK (total_dwelling_units >= 0)
            )
            """
        )

        op.execute(
            """
            CREATE INDEX ix_hdb_property_blk_no ON hdb_property_information (blk_no)
            """
        )
        op.execute(
            """
            CREATE INDEX ix_hdb_property_enriched_addr_id
            ON hdb_property_information (enriched_addr_id)
            """
        )
        op.execute(
            """
            CREATE INDEX ix_hdb_property_hdb_town ON hdb_property_information (hdb_town)
            """
        )
        op.execute(
            """
            CREATE INDEX ix_hdb_property_year_completed
            ON hdb_property_information (year_completed)
            """
        )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_training_readonly') THEN
                GRANT SELECT ON TABLE public.hdb_property_information TO ml_training_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hdb_property_information CASCADE")
