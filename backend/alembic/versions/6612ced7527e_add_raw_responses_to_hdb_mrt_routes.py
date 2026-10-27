"""add_raw_responses_to_hdb_mrt_routes

Revision ID: 6612ced7527e
Revises: 77cb299260ef
Create Date: 2026-03-29 06:16:05.218661
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6612ced7527e'
down_revision: Union[str, None] = '77cb299260ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('hdb_mrt_routes', sa.Column('raw_walk_response', sa.Text(), nullable=True))
    op.add_column('hdb_mrt_routes', sa.Column('raw_drive_response', sa.Text(), nullable=True))
    op.add_column('hdb_mrt_routes', sa.Column('raw_pt_response', sa.Text(), nullable=True))
    op.add_column('hdb_mrt_routes', sa.Column('raw_cycle_response', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('hdb_mrt_routes', 'raw_cycle_response')
    op.drop_column('hdb_mrt_routes', 'raw_pt_response')
    op.drop_column('hdb_mrt_routes', 'raw_drive_response')
    op.drop_column('hdb_mrt_routes', 'raw_walk_response')
