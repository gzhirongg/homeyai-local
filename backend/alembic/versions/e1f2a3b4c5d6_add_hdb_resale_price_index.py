"""Add hdb_resale_price_index (HDB RPI quarterly series).

Revision ID: e1f2a3b4c5d6
Revises: c9d0e1f2a3b4
Create Date: 2026-05-19
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Table may already exist from manual DDL — skip CREATE, still stamp and apply ML grants below.
    if not inspect(conn).has_table("hdb_resale_price_index"):
        op.execute(
            """
            CREATE TABLE hdb_resale_price_index (
                quarter_label   VARCHAR(7)  NOT NULL,
                year            SMALLINT    NOT NULL,
                quarter_num     SMALLINT    NOT NULL CHECK (quarter_num BETWEEN 1 AND 4),
                period_start    DATE        NOT NULL,
                index_value     NUMERIC(8, 2) NOT NULL CHECK (index_value > 0),
                base_reference  TEXT        NOT NULL DEFAULT '2009-Q1=100',
                source          TEXT        NOT NULL DEFAULT 'data.gov.sg',
                source_resource_id TEXT     NOT NULL DEFAULT 'd_14f63e595975691e7c24a27ae4c07c79',
                ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (period_start),
                CONSTRAINT hdb_rpi_quarter_label_fmt
                    CHECK (quarter_label ~ '^[0-9]{4}-Q[1-4]$'),
                CONSTRAINT hdb_rpi_label_matches_parts
                    CHECK (quarter_label = year::text || '-Q' || quarter_num::text),
                UNIQUE (quarter_label),
                UNIQUE (year, quarter_num)
            )
            """
        )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_training_readonly') THEN
                GRANT SELECT ON TABLE public.hdb_resale_price_index TO ml_training_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hdb_resale_price_index")
