"""add enriched_addr_id and block_street to hdb_resale_transactions

Revision ID: c1d4e8f0a2b3
Revises: a0846ab829e0
Create Date: 2026-05-03

Safe if columns / index / FK already exist (manual DDL).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "c1d4e8f0a2b3"
down_revision: Union[str, None] = "a0846ab829e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "hdb_resale_transactions" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("hdb_resale_transactions")}
    if "block_street" not in cols:
        op.add_column(
            "hdb_resale_transactions",
            sa.Column("block_street", sa.Text(), nullable=True),
        )
    if "enriched_addr_id" not in cols:
        op.add_column(
            "hdb_resale_transactions",
            sa.Column("enriched_addr_id", sa.Integer(), nullable=True),
        )

    inspector = inspect(bind)
    existing_ix = {ix["name"] for ix in inspector.get_indexes("hdb_resale_transactions")}
    idx_name = "ix_hdb_resale_transactions_enriched_addr_id"
    if idx_name not in existing_ix:
        op.create_index(
            idx_name,
            "hdb_resale_transactions",
            ["enriched_addr_id"],
            unique=False,
        )

    inspector = inspect(bind)
    fk_names = {fk["name"] for fk in inspector.get_foreign_keys("hdb_resale_transactions")}
    fk_name = "fk_hdb_resale_enriched_addr"
    tables = set(inspector.get_table_names())
    if (
        fk_name not in fk_names
        and "hdb_address_enrichment_onemap" in tables
    ):
        op.create_foreign_key(
            fk_name,
            "hdb_resale_transactions",
            "hdb_address_enrichment_onemap",
            ["enriched_addr_id"],
            ["id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "hdb_resale_transactions" not in inspector.get_table_names():
        return

    fk_names = {fk["name"] for fk in inspector.get_foreign_keys("hdb_resale_transactions")}
    if "fk_hdb_resale_enriched_addr" in fk_names:
        op.drop_constraint(
            "fk_hdb_resale_enriched_addr",
            "hdb_resale_transactions",
            type_="foreignkey",
        )

    existing_ix = {ix["name"] for ix in inspector.get_indexes("hdb_resale_transactions")}
    if "ix_hdb_resale_transactions_enriched_addr_id" in existing_ix:
        op.drop_index(
            "ix_hdb_resale_transactions_enriched_addr_id",
            table_name="hdb_resale_transactions",
        )

    cols = {c["name"] for c in inspector.get_columns("hdb_resale_transactions")}
    if "enriched_addr_id" in cols:
        op.drop_column("hdb_resale_transactions", "enriched_addr_id")
    if "block_street" in cols:
        op.drop_column("hdb_resale_transactions", "block_street")
