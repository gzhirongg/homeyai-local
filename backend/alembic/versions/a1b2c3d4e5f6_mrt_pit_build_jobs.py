"""mrt_pit_build_jobs — per-month PIT snapshot build tracking

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-10

"""

from typing import Sequence, Union

from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mrt_pit_build_jobs (
            tx_year_month VARCHAR(7) PRIMARY KEY,
            pairs_total INTEGER NOT NULL,
            pairs_inserted INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            worker_id TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            error_msg TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_mrt_pit_jobs_status_month
          ON mrt_pit_build_jobs (status, tx_year_month DESC);
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_training_readonly') THEN
                GRANT SELECT ON TABLE public.mrt_pit_build_jobs TO ml_training_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mrt_pit_build_jobs;")
