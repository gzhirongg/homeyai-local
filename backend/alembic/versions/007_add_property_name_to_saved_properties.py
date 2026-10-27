"""add property nickname to saved properties

Revision ID: 008_add_property_nickname
Revises: c2d62c48c75f
Create Date: 2026-05-12 23:48:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '008_add_property_nickname'
down_revision = 'c2d62c48c75f'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('saved_properties', sa.Column('nickname', sa.String(), nullable=True))

def downgrade() -> None:
    op.drop_column('saved_properties', 'nickname')
