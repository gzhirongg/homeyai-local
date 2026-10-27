"""add postal_code to hdb_resale_transactions

Revision ID: 007_hdb_postal
Revises: 006_add_user_is_banned
Create Date: 2026-03-28 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '007_hdb_postal'
down_revision = '006_add_user_is_banned'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('hdb_resale_transactions', sa.Column('postal_code', sa.String(), nullable=True))
    op.create_index(op.f('ix_hdb_resale_transactions_postal_code'), 'hdb_resale_transactions', ['postal_code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_hdb_resale_transactions_postal_code'), table_name='hdb_resale_transactions')
    op.drop_column('hdb_resale_transactions', 'postal_code')
