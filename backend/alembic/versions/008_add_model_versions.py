"""Add model_versions registry for production model pointer.

Revision ID: 008_add_model_versions
Revises: 007_hdb_postal

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008_add_model_versions"
down_revision: Union[str, None] = "007_hdb_postal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("env", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("experiment_id", sa.String(), nullable=True),
        sa.Column("feature_set_id", sa.String(), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("rmse", sa.Float(), nullable=True),
        sa.Column(
            "is_production",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "registered_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("promoted_at", sa.DateTime(), nullable=True),
        sa.Column("promoted_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["promoted_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key", name="uq_model_versions_object_key"),
    )
    op.create_index(
        "ix_model_versions_env_production",
        "model_versions",
        ["env", "is_production"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_model_versions_env_production", table_name="model_versions")
    op.drop_table("model_versions")
