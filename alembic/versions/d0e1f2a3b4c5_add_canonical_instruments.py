"""Add canonical instruments and provider mappings.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-20 05:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("instruments"):
        op.create_table(
            "instruments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("krx_short_code", sa.String(length=20), nullable=False),
            sa.Column("isin", sa.String(length=20), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("market", sa.String(length=20), nullable=False),
            sa.Column("security_type", sa.String(length=20), nullable=False),
            sa.Column("listed_at", sa.Date(), nullable=True),
            sa.Column("delisted_at", sa.Date(), nullable=True),
            sa.Column("listing_status", sa.String(length=30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("krx_short_code", name="uq_instruments_krx_short_code"),
            sa.UniqueConstraint("isin", name="uq_instruments_isin"),
        )
        op.create_index(
            "ix_instruments_market_type_status",
            "instruments",
            ["market", "security_type", "listing_status"],
        )

    if not inspector.has_table("provider_symbols"):
        op.create_table(
            "provider_symbols",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("instrument_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("provider_symbol", sa.String(length=50), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("mapping_status", sa.String(length=30), nullable=False),
            sa.Column("evidence_snapshot_id", sa.Integer(), nullable=True),
            sa.Column("evidence", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
            sa.ForeignKeyConstraint(["evidence_snapshot_id"], ["krx_universe_snapshots.id"]),
            sa.UniqueConstraint(
                "instrument_id", "provider", "provider_symbol", "valid_from",
                name="uq_provider_symbols_version",
            ),
        )
        op.create_index(
            "ix_provider_symbols_provider_status",
            "provider_symbols",
            ["provider", "mapping_status"],
        )

    if not inspector.has_table("universe_exclusions"):
        op.create_table(
            "universe_exclusions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("instrument_id", sa.Integer(), nullable=False),
            sa.Column("scope", sa.String(length=30), nullable=False),
            sa.Column("reason_code", sa.String(length=100), nullable=False),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
            sa.Column("evidence_snapshot_id", sa.Integer(), nullable=True),
            sa.Column("evidence", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
            sa.ForeignKeyConstraint(["evidence_snapshot_id"], ["krx_universe_snapshots.id"]),
            sa.UniqueConstraint(
                "instrument_id", "scope", "reason_code", "valid_from",
                name="uq_universe_exclusions_version",
            ),
        )
        op.create_index(
            "ix_universe_exclusions_scope_active",
            "universe_exclusions",
            ["scope", "valid_to"],
        )
    op.add_column("symbols", sa.Column("instrument_id", sa.Integer(), nullable=True))
    op.add_column("symbols", sa.Column("legacy_code", sa.String(length=20), nullable=True))
    op.create_foreign_key("fk_symbols_instrument_id", "symbols", "instruments", ["instrument_id"], ["id"])
    op.create_index("ix_symbols_instrument_id", "symbols", ["instrument_id"])
    op.create_index("ix_symbols_legacy_code", "symbols", ["legacy_code"])


def downgrade() -> None:
    op.drop_index("ix_symbols_legacy_code", table_name="symbols")
    op.drop_index("ix_symbols_instrument_id", table_name="symbols")
    op.drop_constraint("fk_symbols_instrument_id", "symbols", type_="foreignkey")
    op.drop_column("symbols", "legacy_code")
    op.drop_column("symbols", "instrument_id")
    op.drop_index("ix_universe_exclusions_scope_active", table_name="universe_exclusions")
    op.drop_table("universe_exclusions")
    op.drop_index("ix_provider_symbols_provider_status", table_name="provider_symbols")
    op.drop_table("provider_symbols")
    op.drop_index("ix_instruments_market_type_status", table_name="instruments")
    op.drop_table("instruments")
