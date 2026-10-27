"""Add HDB estate maturity sidecars (completions FY, town land km2, town-month panel)."""

from typing import Sequence, Union

from alembic import op


revision: str = "d4e3f2a1b9c8"
down_revision: Union[str, None] = "a8f7e6d5c4b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hdb_resale_town_planning_area (
            town_normalized TEXT NOT NULL,
            pln_area_n TEXT NOT NULL,
            PRIMARY KEY (town_normalized, pln_area_n)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hdb_resale_town_land_area_km2 (
            town_normalized TEXT PRIMARY KEY,
            land_area_sq_km DOUBLE PRECISION NOT NULL
                CHECK (land_area_sq_km > 0),
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hdb_town_completion_fy (
            financial_year SMALLINT NOT NULL,
            fy_start_date DATE NOT NULL,
            fy_end_date DATE NOT NULL,
            town_normalized TEXT NOT NULL,
            scheme TEXT NOT NULL,
            status TEXT NOT NULL,
            n_units INTEGER NOT NULL CHECK (n_units >= 0),
            source TEXT NOT NULL DEFAULT 'data.gov.sg',
            source_resource_id TEXT NOT NULL DEFAULT 'd_9bbcd0c9b0351c7f41c9bfdcdc746668',
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (financial_year, town_normalized, scheme, status)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hdb_town_completion_fy_town ON hdb_town_completion_fy (town_normalized)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_hdb_town_completion_fy_status ON hdb_town_completion_fy (status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS hdb_estate_maturity_by_town_month (
            town_normalized TEXT NOT NULL,
            year_month TEXT NOT NULL,
            avg_residential_block_age_years DOUBLE PRECISION,
            town_completed_residential_units_stock INTEGER,
            town_land_area_km2 DOUBLE PRECISION,
            town_dwelling_unit_density DOUBLE PRECISION,
            town_units_under_construction INTEGER,
            town_hdb_completed_units_roll36m INTEGER,
            town_supply_maturity_ratio DOUBLE PRECISION,
            materialized_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (town_normalized, year_month),
            CONSTRAINT chk_estate_maturity_year_month
                CHECK (year_month ~ '^[0-9]{4}-[0-9]{2}$')
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_hdb_estate_maturity_ym
        ON hdb_estate_maturity_by_town_month (year_month)
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_training_readonly') THEN
                GRANT SELECT ON TABLE public.hdb_resale_town_planning_area TO ml_training_readonly;
                GRANT SELECT ON TABLE public.hdb_resale_town_land_area_km2 TO ml_training_readonly;
                GRANT SELECT ON TABLE public.hdb_town_completion_fy TO ml_training_readonly;
                GRANT SELECT ON TABLE public.hdb_estate_maturity_by_town_month TO ml_training_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hdb_estate_maturity_by_town_month CASCADE")
    op.execute("DROP TABLE IF EXISTS hdb_town_completion_fy CASCADE")
    op.execute("DROP TABLE IF EXISTS hdb_resale_town_land_area_km2 CASCADE")
    op.execute("DROP TABLE IF EXISTS hdb_resale_town_planning_area CASCADE")
