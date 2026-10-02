"""Add immutable materialized backtest datasets.

Revision ID: l5e6f7a8b9c0
Revises: k4d5e6f7a8b9
Create Date: 2026-09-06 06:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "k4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("backtest_datasets"):
        op.create_table("backtest_datasets", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("dataset_id", sa.String(80), nullable=False), sa.Column("manifest_hash", sa.String(64), nullable=False), sa.Column("range_start", sa.Date(), nullable=False), sa.Column("range_end", sa.Date(), nullable=False), sa.Column("markets", sa.JSON(), nullable=False), sa.Column("reconstruction_mode", sa.String(40), nullable=False), sa.Column("as_known_at", sa.DateTime(timezone=True)), sa.Column("adjustment_policy", sa.String(100), nullable=False), sa.Column("policy_version", sa.String(100), nullable=False), sa.Column("preparation_start", sa.Date()), sa.Column("manifest", sa.JSON(), nullable=False), sa.Column("status", sa.String(20), nullable=False, server_default="active"), sa.Column("retention_until", sa.DateTime(timezone=True)), sa.Column("expired_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("dataset_id", name="uq_backtest_datasets_dataset_id"), sa.UniqueConstraint("manifest_hash", name="uq_backtest_datasets_manifest_hash"))
        for name, columns in (("ix_backtest_datasets_dataset_id", ["dataset_id"]), ("ix_backtest_datasets_manifest_hash", ["manifest_hash"]), ("ix_backtest_datasets_status_retention", ["status", "retention_until"]), ("ix_backtest_datasets_range", ["range_start", "range_end"])):
            op.create_index(name, "backtest_datasets", columns)
    if not inspector.has_table("backtest_dataset_prices"):
        op.create_table("backtest_dataset_prices", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("backtest_dataset_id", sa.Integer(), nullable=False), sa.Column("instrument_id", sa.Integer(), nullable=False), sa.Column("source_symbol_id", sa.Integer(), nullable=False), sa.Column("source_observation_id", sa.Integer()), sa.Column("code", sa.String(20), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("market", sa.String(20), nullable=False), sa.Column("trade_date", sa.Date(), nullable=False), sa.Column("open", sa.Numeric(18, 4), nullable=False), sa.Column("high", sa.Numeric(18, 4), nullable=False), sa.Column("low", sa.Numeric(18, 4), nullable=False), sa.Column("close", sa.Numeric(18, 4), nullable=False), sa.Column("volume", sa.BigInteger(), nullable=False), sa.Column("change_rate", sa.Numeric(10, 4), nullable=False), sa.Column("provider", sa.String(100), nullable=False), sa.Column("adjustment_type", sa.String(50)), sa.Column("source_payload_hash", sa.String(64)), sa.ForeignKeyConstraint(["backtest_dataset_id"], ["backtest_datasets.id"]), sa.UniqueConstraint("backtest_dataset_id", "source_symbol_id", "trade_date", name="uq_backtest_dataset_price_symbol_date"))
        for name, columns in (("ix_backtest_dataset_prices_backtest_dataset_id", ["backtest_dataset_id"]), ("ix_backtest_dataset_prices_instrument_id", ["instrument_id"]), ("ix_backtest_dataset_prices_source_symbol_id", ["source_symbol_id"]), ("ix_backtest_dataset_prices_source_observation_id", ["source_observation_id"]), ("ix_backtest_dataset_prices_code", ["code"]), ("ix_backtest_dataset_prices_market", ["market"]), ("ix_backtest_dataset_prices_trade_date", ["trade_date"]), ("ix_backtest_dataset_prices_dataset_date", ["backtest_dataset_id", "trade_date"])):
            op.create_index(name, "backtest_dataset_prices", columns)
    if not inspector.has_table("backtest_dataset_memberships"):
        op.create_table("backtest_dataset_memberships", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("backtest_dataset_id", sa.Integer(), nullable=False), sa.Column("instrument_id", sa.Integer(), nullable=False), sa.Column("trade_date", sa.Date(), nullable=False), sa.Column("market", sa.String(20), nullable=False), sa.Column("security_type", sa.String(20), nullable=False), sa.Column("membership_evidence_state", sa.String(20), nullable=False), sa.Column("trading_status", sa.String(40), nullable=False), sa.Column("price_expectation", sa.String(40), nullable=False), sa.Column("event_revision_hashes", sa.JSON(), nullable=False), sa.ForeignKeyConstraint(["backtest_dataset_id"], ["backtest_datasets.id"]), sa.UniqueConstraint("backtest_dataset_id", "instrument_id", "trade_date", name="uq_backtest_dataset_membership_date"))
        for name, columns in (("ix_backtest_dataset_memberships_backtest_dataset_id", ["backtest_dataset_id"]), ("ix_backtest_dataset_memberships_instrument_id", ["instrument_id"]), ("ix_backtest_dataset_memberships_trade_date", ["trade_date"]), ("ix_backtest_dataset_memberships_market", ["market"]), ("ix_backtest_dataset_memberships_dataset_date", ["backtest_dataset_id", "trade_date"])):
            op.create_index(name, "backtest_dataset_memberships", columns)


def downgrade() -> None:
    op.drop_table("backtest_dataset_memberships")
    op.drop_table("backtest_dataset_prices")
    op.drop_table("backtest_datasets")
