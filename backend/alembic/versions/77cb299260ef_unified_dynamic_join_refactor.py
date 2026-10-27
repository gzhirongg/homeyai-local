"""unified_dynamic_join_refactor

Revision ID: 77cb299260ef
Revises: 007_hdb_postal
Create Date: 2026-03-29 05:48:46.527737
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '77cb299260ef'
down_revision: Union[str, None] = '007_hdb_postal'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Older VM databases had this table from manual DDL. Reconstruct it for
    # clean installs before applying the recorded rename.
    if 'onemap_address_resolution' not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            'onemap_address_resolution',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('block', sa.String()),
            sa.Column('street_name', sa.String()),
            sa.Column('postal_code', sa.String()),
            sa.Column('latitude', sa.Float()),
            sa.Column('longitude', sa.Float()),
            sa.Column('results_count', sa.Integer(), server_default='0'),
            sa.Column('query_sent', sa.String(), nullable=False),
            sa.Column('raw_response', sa.Text(), nullable=False),
            sa.Column('last_attempt_at', sa.DateTime()),
            sa.Column('attempt_count', sa.Integer(), server_default='1'),
            sa.UniqueConstraint('block', 'street_name'),
        )
    # 1. Rename the address resolution table
    op.rename_table('onemap_address_resolution', 'hdb_address_enrichment_onemap')
    
    # 2. Create the hdb_mrt_routes table
    op.create_table('hdb_mrt_routes',
        sa.Column('hdb_addr_id', sa.INTEGER(), nullable=False),
        sa.Column('mrt_stn_id', sa.INTEGER(), nullable=False),
        sa.Column('haversine_distance_m', sa.FLOAT(), nullable=True),
        sa.Column('walk_distance_m', sa.INTEGER(), nullable=True),
        sa.Column('walk_time_mins', sa.INTEGER(), nullable=True),
        sa.Column('drive_distance_m', sa.INTEGER(), nullable=True),
        sa.Column('drive_time_mins', sa.INTEGER(), nullable=True),
        sa.Column('pt_distance_m', sa.INTEGER(), nullable=True),
        sa.Column('pt_time_mins', sa.INTEGER(), nullable=True),
        sa.Column('cycle_distance_m', sa.INTEGER(), nullable=True),
        sa.Column('cycle_time_mins', sa.INTEGER(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.PrimaryKeyConstraint('hdb_addr_id', 'mrt_stn_id', name=op.f('hdb_mrt_routes_pkey')),
        sa.ForeignKeyConstraint(['hdb_addr_id'], ['hdb_address_enrichment_onemap.id']),
    )

    # 3. Clean up the hdb_resale_transactions table
    op.drop_index('ix_hdb_resale_transactions_postal_code', table_name='hdb_resale_transactions')
    op.create_index(op.f('ix_hdb_resale_transactions_block'), 'hdb_resale_transactions', ['block'], unique=False)
    op.create_index(op.f('ix_hdb_resale_transactions_street_name'), 'hdb_resale_transactions', ['street_name'], unique=False)
    
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('hdb_resale_transactions')}
    if 'longitude' in columns:
        op.drop_column('hdb_resale_transactions', 'longitude')
    op.drop_column('hdb_resale_transactions', 'postal_code')
    if 'latitude' in columns:
        op.drop_column('hdb_resale_transactions', 'latitude')

def downgrade() -> None:
    # 1. Restore hdb_resale_transactions columns
    op.add_column('hdb_resale_transactions', sa.Column('latitude', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True))
    op.add_column('hdb_resale_transactions', sa.Column('postal_code', sa.VARCHAR(), autoincrement=False, nullable=True))
    op.add_column('hdb_resale_transactions', sa.Column('longitude', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True))
    
    op.drop_index(op.f('ix_hdb_resale_transactions_street_name'), table_name='hdb_resale_transactions')
    op.drop_index(op.f('ix_hdb_resale_transactions_block'), table_name='hdb_resale_transactions')
    op.create_index('ix_hdb_resale_transactions_postal_code', 'hdb_resale_transactions', ['postal_code'], unique=False)

    # 2. Drop the hdb_mrt_routes table
    op.drop_table('hdb_mrt_routes')

    # 3. Rename address resolution back
    op.rename_table('hdb_address_enrichment_onemap', 'onemap_address_resolution')
