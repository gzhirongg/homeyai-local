"""grant ml_training_readonly SELECT on hdb_resale_price_index

Follow-up so DBs stamped by an earlier revision body still obtain the privilege
(without relying on CREATE TABLE running again).

Revision ID: fef1c8d93a41
Revises: e1f2a3b4c5d6
Create Date: 2026-05-19

"""

from typing import Sequence, Union

from alembic import op


revision: str = "fef1c8d93a41"
down_revision: Union[str, None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_grant_block = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_training_readonly') THEN
        GRANT SELECT ON TABLE public.hdb_resale_price_index TO ml_training_readonly;
    END IF;
END $$;
"""

_revoke_block = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ml_training_readonly') THEN
        REVOKE SELECT ON TABLE public.hdb_resale_price_index FROM ml_training_readonly;
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_grant_block)


def downgrade() -> None:
    op.execute(_revoke_block)
