"""Add immutable source-backed historical listing event revisions.

Revision ID: j3c4d5e6f7a8
Revises: h2b3c4d5e6f7
Create Date: 2026-09-05 23:50:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "h2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("listing_events"):
        return
    op.create_table(
        "listing_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("source_contract_version", sa.String(length=100), nullable=False),
        sa.Column("source_record_key", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_file_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_trading_date", sa.Date(), nullable=True),
        sa.Column("market", sa.String(length=20), nullable=True),
        sa.Column("market_to", sa.String(length=20), nullable=True),
        sa.Column("provider_code", sa.String(length=50), nullable=True),
        sa.Column("provider_code_to", sa.String(length=50), nullable=True),
        sa.Column("trading_status", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_state", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["listing_events.id"]),
        sa.UniqueConstraint("source", "source_record_key", "content_hash", name="uq_listing_events_source_record_hash"),
    )
    op.create_index("ix_listing_events_instrument_id", "listing_events", ["instrument_id"])
    op.create_index("ix_listing_events_instrument_effective", "listing_events", ["instrument_id", "effective_from"])
    op.create_index("ix_listing_events_source_record", "listing_events", ["source", "source_record_key"])


def downgrade() -> None:
    op.drop_index("ix_listing_events_source_record", table_name="listing_events")
    op.drop_index("ix_listing_events_instrument_effective", table_name="listing_events")
    op.drop_index("ix_listing_events_instrument_id", table_name="listing_events")
    op.drop_table("listing_events")
